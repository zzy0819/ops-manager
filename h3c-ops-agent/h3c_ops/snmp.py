#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标准 SNMP 团体名配置（Comware V7 为主，兼容 V5 语法）。

标准动作（幂等）：
    1. 打开 snmp-agent，设置 v2c
    2. 设置 sys-info contact / location（资产可读性）
    3. 建/补 基本 ACL（默认 2001），只放行监控平台 IP
    4. 配置只读团体名，并绑定 ACL
    5. 配置 trap 目的（指向 Zabbix），开启 trap
    6. save force 落盘（可选）
默认不配写团体名——读写权限会给监控平台，安全上没必要。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .ssh import H3CSession, shorten

CMD_SNMP_CONF = "display current-configuration | include snmp-agent"

STATUS_OK, STATUS_SKIP, STATUS_DRY, STATUS_FAIL = "成功", "无变化", "预览", "失败"

COMMUNITY_RE = re.compile(
    r"snmp-agent\s+community\s+(read|write)\s+(?:(simple|cipher)\s+)?(\S+?)(?:\s+acl\s+(\d+))?\s*$",
    re.M,
)
VERSION_RE = re.compile(r"snmp-agent\s+sys-info\s+version\s+(.+)")
CONTACT_RE = re.compile(r"snmp-agent\s+sys-info\s+contact\s+(.+)")
LOCATION_RE = re.compile(r"snmp-agent\s+sys-info\s+location\s+(.+)")
TRAP_RE = re.compile(
    r"snmp-agent\s+target-host\s+trap\s+address\s+udp-domain\s+(\S+)(?:.*?udp-port\s+(\d+))?",
    re.M,
)


@dataclass
class ApplyResult:
    status: str
    detail: str
    commands: List[str] = field(default_factory=list)
    acl: int = 0
    verified: Optional[bool] = None
    warnings: List[str] = field(default_factory=list)


def parse_config_state(text: str) -> Dict[str, Any]:
    """解析 display current-configuration | include snmp-agent 的输出。"""
    text = text or ""
    state: Dict[str, Any] = {
        "has_snmp": bool(re.search(r"snmp-agent", text, re.I)),
        "v2c": False,
        "v3": False,
        "read_communities": [],
        "write_communities": [],
        "community_acl": {},
        "cipher_communities": [],
        "trap_targets": [],
        "contact": "",
        "location": "",
        "trap_enabled": False,
    }
    if not state["has_snmp"]:
        return state

    for match in VERSION_RE.finditer(text):
        versions = match.group(1).lower()
        state["v2c"] = "v2c" in versions or "all" in versions
        state["v3"] = "v3" in versions

    for match in COMMUNITY_RE.finditer(text):
        mode, kind, value, acl = match.groups()
        if kind == "cipher":
            state["cipher_communities"].append(value)
            if acl:
                state["community_acl"][value] = int(acl)
            continue
        key = "read_communities" if mode == "read" else "write_communities"
        state[key].append(value)
        if acl:
            state["community_acl"][value] = int(acl)

    match = CONTACT_RE.search(text)
    if match:
        state["contact"] = match.group(1).strip()
    match = LOCATION_RE.search(text)
    if match:
        state["location"] = match.group(1).strip()
    state["trap_targets"] = [m.group(1) for m in TRAP_RE.finditer(text)]
    state["trap_enabled"] = bool(re.search(r"snmp-agent\s+trap\s+enable", text))
    return state


def validate_community(value: str) -> Optional[str]:
    """返回不合法原因，合法则 None。"""
    if not value:
        return "团体名为空"
    if len(value) < 8:
        return "团体名建议至少 8 位（会降低被爆破风险）"
    if re.search(r"\s", value):
        return "团体名不能包含空格"
    return None


def build_acl_commands(acl_number: int, sources: List[str], existing_rules: Dict[int, str]) -> List[str]:
    """生成建/补 ACL 的命令（自动跳过已存在的放行规则）。"""
    commands = [f"acl basic {acl_number}"]
    next_number = (max(existing_rules) + 10) if existing_rules else 5
    for ip in sources:
        if any(_rule_covers(rule_text, ip) for rule_text in existing_rules.values()):
            continue
        commands.append(f"rule {next_number} permit source {ip} 0")
        next_number += 10
    commands.append("quit")
    if len(commands) == 2:  # 只有 acl + quit，说明无需变更
        return []
    return commands


def _rule_covers(rule_text: str, ip: str) -> bool:
    return bool(re.search(rf"permit\s+source\s+{re.escape(ip)}(?:\s+0)?(?:\s|$)", rule_text))


def parse_acl(text: str) -> Tuple[bool, Dict[int, str]]:
    """返回 (是否存在, {规则号: 规则内容})。"""
    if not text or "does not exist" in text.lower() or "not exist" in text.lower():
        return False, {}
    rules: Dict[int, str] = {}
    exists = bool(re.search(r"\bACL\b", text, re.I))
    for match in re.finditer(r"^\s*rule\s+(\d+)\s+(.+)$", text, re.M):
        rules[int(match.group(1))] = match.group(2).strip()
    return exists, rules


def build_commands(
    snmp_cfg: Dict[str, Any],
    community: str,
    acl_number: int = 0,
) -> List[str]:
    """生成 SNMP 配置命令序列（不含 ACL 部分）。"""
    commands = ["snmp-agent", "snmp-agent sys-info version v2c"]

    contact = str(snmp_cfg.get("contact") or "").strip()
    if contact:
        commands.append(f"snmp-agent sys-info contact {contact}")
    location = str(snmp_cfg.get("location") or "").strip()
    if location:
        commands.append(f"snmp-agent sys-info location {location}")

    if snmp_cfg.get("disable_complexity_check"):
        commands.append("snmp-agent community complexity-check disable")

    read_cmd = f"snmp-agent community read simple {community}"
    if acl_number:
        read_cmd += f" acl {acl_number}"
    commands.append(read_cmd)

    write_community = str(snmp_cfg.get("write_community") or "").strip()
    if write_community:
        write_cmd = f"snmp-agent community write simple {write_community}"
        if acl_number:
            write_cmd += f" acl {acl_number}"
        commands.append(write_cmd)

    if snmp_cfg.get("enable_trap") and snmp_cfg.get("trap_target"):
        commands.append("snmp-agent trap enable")
        port = int(snmp_cfg.get("trap_port") or 162)
        commands.append(
            f"snmp-agent target-host trap address udp-domain {snmp_cfg['trap_target']} "
            f"udp-port {port} params securityname {community} v2c"
        )
    return commands


def is_compliant(state: Dict[str, Any], community: str, acl_number: int, snmp_cfg: Dict[str, Any]) -> bool:
    if not state.get("has_snmp") or not state.get("v2c"):
        return False
    if community not in state.get("read_communities", []):
        return False
    if acl_number and state.get("community_acl", {}).get(community) != acl_number:
        return False
    if snmp_cfg.get("enable_trap") and snmp_cfg.get("trap_target"):
        if snmp_cfg["trap_target"] not in state.get("trap_targets", []):
            return False
        if not state.get("trap_enabled"):
            return False
    return True


def apply(
    session: H3CSession,
    snmp_cfg: Dict[str, Any],
    device_community: str = "",
    dry_run: bool = True,
) -> ApplyResult:
    """下发标准团体名。dry_run=True 时只返回将要执行的命令。"""
    community = (device_community or snmp_cfg.get("read_community") or "").strip()
    problem = validate_community(community)
    if problem:
        return ApplyResult(STATUS_FAIL, problem)

    warnings: List[str] = []
    acl_number = int(snmp_cfg.get("acl_number") or 0)
    acl_sources = [s for s in (snmp_cfg.get("acl_sources") or []) if s]

    current_text, error = session.send_safe(CMD_SNMP_CONF, timeout=40)
    if error:
        return ApplyResult(STATUS_FAIL, f"读取 SNMP 配置失败: {error}")
    state = parse_config_state(current_text)

    others = [c for c in state["read_communities"] if c != community]
    if others:
        warnings.append(f"设备上还有非标准只读团体名: {', '.join(others[:3])}（建议确认后手工清理）")
    if state["write_communities"]:
        warnings.append("设备上已存在写团体名（rw 权限），建议按需收紧")

    acl_commands: List[str] = []
    if acl_number and acl_sources:
        acl_text, _ = session.send_safe(f"display acl {acl_number}", timeout=25)
        exists, rules = parse_acl(acl_text)
        acl_commands = build_acl_commands(acl_number, acl_sources, rules if exists else {})
        if exists and not acl_commands:
            pass
        elif exists:
            warnings.append(f"ACL {acl_number} 已存在，仅补齐缺失的放行规则")

    commands = acl_commands + build_commands(snmp_cfg, community, acl_number)
    compliant = is_compliant(state, community, acl_number, snmp_cfg) and not acl_commands
    if compliant:
        return ApplyResult(STATUS_SKIP, "已符合标准配置（v2c + 团体名 + ACL + trap），跳过", commands, acl_number, True, warnings)

    if dry_run:
        return ApplyResult(
            STATUS_DRY,
            f"将下发 {len(commands)} 条命令（预览模式，未做任何变更）",
            commands, acl_number, None, warnings,
        )

    try:
        session.config(commands, stop_on_error=True)
    except Exception as e:  # noqa: BLE001
        return ApplyResult(STATUS_FAIL, f"下发失败: {shorten(str(e), 200)}", commands, acl_number, False, warnings)

    saved_note = ""
    if snmp_cfg.get("save_after_apply", True):
        save_result = session.save()
        saved_note = "；" + save_result.detail
        if not save_result.ok:
            return ApplyResult(
                STATUS_FAIL,
                f"命令已下发但保存失败: {save_result.detail}",
                commands, acl_number, None, warnings,
            )

    verify_text, _ = session.send_safe(CMD_SNMP_CONF, timeout=40)
    verified = is_compliant(parse_config_state(verify_text), community, acl_number, snmp_cfg)
    if not verified:
        return ApplyResult(
            STATUS_FAIL,
            f"命令已下发，但回读校验未通过（请检查设备是否支持对应语法）{saved_note}",
            commands, acl_number, False, warnings,
        )
    return ApplyResult(
        STATUS_OK,
        f"团体名 {community} 已生效，ACL {acl_number or '未绑定'}{saved_note}",
        commands, acl_number, True, warnings,
    )
