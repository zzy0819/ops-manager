#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置加载：JSON + 默认值深合并 + 环境变量覆盖。"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict


class ConfigError(Exception):
    """配置文件缺失或内容不合法。"""


DEFAULTS: Dict[str, Any] = {
    "inventory_file": "devices.xlsx",
    "credentials": {"username": "", "password": "", "secret": "", "candidates": []},
    "global": {
        "concurrency": 8,
        "connect_timeout": 15,
        "command_timeout": 30,
        "save_timeout": 180,
        "run_dir": "runs",
        "backup_dir": "backups",
    },
    "inspect": {
        "collect_optical": False,
        "thresholds": {
            "cpu_percent": 80,
            "memory_percent": 85,
            "temperature": 60,
            "down_port_count": 0,
        },
    },
    "snmp": {
        "read_community": "",
        "write_community": "",
        "acl_number": 0,
        "acl_sources": [],
        "contact": "",
        "location": "",
        "disable_complexity_check": True,
        "enable_trap": False,
        "trap_target": "",
        "trap_port": 162,
        "save_after_apply": True,
    },
    "zabbix": {
        "url": "",
        "user": "",
        "password": "",
        "api_token": "",
        "verify_tls": True,
        "host_group": "网络设备/华三交换机",
        "template_candidates": ["H3C Comware by SNMP"],
        "snmp_port": 161,
        "community_macro": "{$SNMP_COMMUNITY}",
        "proxy_name": "",
        "host_name_source": "sysname",
        "overwrite_interface": False,
    },
    "backup": {"keep": 30, "save_before_backup": True},
}


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """override 覆盖 base，字典递归合并，其余类型直接替换。"""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    """支持 cfg.get('zabbix.url') 点号取值。"""

    def __init__(self, data: Dict[str, Any], path: Path | None = None):
        self.data = data
        self.path = path

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node if node is not None else default

    def section(self, name: str) -> Dict[str, Any]:
        value = self.data.get(name)
        return value if isinstance(value, dict) else {}

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    # ---------------- 常用派生值 ----------------
    @property
    def base_dir(self) -> Path:
        return self.path.parent if self.path else Path.cwd()

    def resolve(self, value: str) -> Path:
        """相对路径按配置文件所在目录解析。"""
        p = Path(value)
        return p if p.is_absolute() else (self.base_dir / p)


def load_config(path: str | os.PathLike | None = None) -> Config:
    if path:
        config_path = Path(path)
        if not config_path.exists():
            raise ConfigError(f"配置文件不存在: {config_path.resolve()}")
    else:
        candidates = [Path("config.json"), Path(__file__).resolve().parent.parent / "config.json"]
        config_path = next((p for p in candidates if p.exists()), None)
        if config_path is None:
            raise ConfigError(
                "未找到配置文件 config.json。\n"
                "请先执行：python run.py init   （会生成 config.json 与 devices.xlsx 模板）"
            )

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"配置文件 JSON 语法错误（{config_path}）: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件顶层必须是对象: {config_path}")

    data = _merge(DEFAULTS, raw)

    # 环境变量覆盖，避免把密码写进文件
    env_map = {
        "H3C_USERNAME": ("credentials", "username"),
        "H3C_PASSWORD": ("credentials", "password"),
        "H3C_SECRET": ("credentials", "secret"),
        "ZABBIX_USER": ("zabbix", "user"),
        "ZABBIX_PASSWORD": ("zabbix", "password"),
        "ZABBIX_TOKEN": ("zabbix", "api_token"),
    }
    for env_key, (section, key) in env_map.items():
        value = os.environ.get(env_key)
        if value:
            data.setdefault(section, {})[key] = value

    cfg = Config(data, config_path)
    _normalise(cfg)
    return cfg


def _normalise(cfg: Config) -> None:
    g = cfg.section("global")
    g["concurrency"] = max(1, min(int(g.get("concurrency", 8) or 8), 50))
    for key in ("connect_timeout", "command_timeout", "save_timeout"):
        g[key] = max(5, int(g.get(key, 30) or 30))

    c = cfg.section("credentials")
    c["candidates"] = _normalise_candidates(c.get("candidates"))

    z = cfg.section("zabbix")
    if z.get("url"):
        z["url"] = str(z["url"]).rstrip("/")

    s = cfg.section("snmp")
    if isinstance(s.get("acl_sources"), str):
        s["acl_sources"] = [s["acl_sources"]]
    s["acl_number"] = int(s.get("acl_number", 0) or 0)
    if not s.get("acl_sources"):
        s["acl_number"] = 0

    b = cfg.section("backup")
    b["keep"] = max(1, int(b.get("keep", 30) or 30))


def _normalise_candidates(raw: Any) -> list[Dict[str, str]]:
    """候选账号支持两种写法，统一成 [{'username','password','secret'}]。"""
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    out: list[Dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            user = str(item.get("username") or item.get("user") or "").strip()
            password = str(item.get("password") or "")
            secret = str(item.get("secret") or "")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            user, password = str(item[0] or "").strip(), str(item[1] or "")
            secret = str(item[2] or "") if len(item) > 2 else ""
        else:
            continue
        if user and password:
            out.append({"username": user, "password": password, "secret": secret})
    return out


def require(cfg: Config, *dotted_keys: str) -> list[str]:
    """返回缺失的必填项（值为空字符串/空列表）。"""
    missing = []
    for key in dotted_keys:
        value = cfg.get(key)
        if value in (None, "", [], {}):
            missing.append(key)
    return missing
