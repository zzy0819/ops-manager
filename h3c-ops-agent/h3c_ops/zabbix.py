#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zabbix 接入：主机组 / 模板 / SNMP 接口 / 宏，全部走官方 JSON-RPC API。

设计要点：
    * 先查后改（幂等）：已达标的主机不做任何写操作
    * 接入前生成"变更计划"，dry-run 只打印计划
    * 同名主机但 IP 不一致时默认不覆盖，直接报冲突（避免把别的设备改坏）
    * host.update 只做"增量合并"，不会把主机已有的组/模板/宏删掉
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests

STATUS_OK, STATUS_SKIP, STATUS_DRY, STATUS_FAIL, STATUS_CONFLICT = (
    "成功", "无变化", "预览", "失败", "冲突",
)


class ZabbixError(Exception):
    """API 调用失败。"""


class ZabbixAPI:
    def __init__(
        self,
        url: str,
        user: str = "",
        password: str = "",
        token: str = "",
        verify_tls: bool = True,
        timeout: int = 30,
    ):
        if not url:
            raise ZabbixError("未配置 zabbix.url")
        self.endpoint = url.rstrip("/") + "/api_jsonrpc.php"
        self.user = user
        self.password = password
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = verify_tls
        self.auth = ""
        self._id = 0
        self._version: Optional[Tuple[int, ...]] = None

    # ------------------------------------------------------------ 底层调用 --
    def _post(self, method: str, params: Any, auth: str = "") -> Any:
        self._id += 1
        payload: Dict[str, Any] = {
            "jsonrpc": "2.0", "method": method, "params": params, "id": self._id,
        }
        headers = {"Content-Type": "application/json-rpc"}
        effective_auth = auth or self.auth
        if effective_auth:
            if self._version and self._version < (6, 4):
                payload["auth"] = effective_auth
            else:
                headers["Authorization"] = f"Bearer {effective_auth}"

        try:
            response = self.session.post(
                self.endpoint, data=json.dumps(payload), headers=headers, timeout=self.timeout
            )
        except requests.RequestException as e:
            raise ZabbixError(f"连接 Zabbix 失败（{self.endpoint}）: {e}") from e

        if response.status_code == 412:
            raise ZabbixError("Zabbix 返回 412：认证信息缺失或已过期（检查 token / 账号密码）")
        if response.status_code >= 400:
            raise ZabbixError(f"Zabbix HTTP {response.status_code}: {response.text[:200]}")
        try:
            body = response.json()
        except ValueError as e:
            raise ZabbixError(f"Zabbix 返回非 JSON（地址是否写错？应为 http://ip/zabbix）: {response.text[:120]}") from e
        if "error" in body:
            err = body["error"]
            detail = err.get("data", "")
            raise ZabbixError(f"{err.get('message', 'API 错误')}: {detail}")
        return body.get("result")

    def version(self) -> Tuple[int, ...]:
        if self._version is None:
            raw = self._post("apiinfo.version", {}, auth="")
            parts = []
            for chunk in str(raw).split("."):
                digits = "".join(ch for ch in chunk if ch.isdigit())
                parts.append(int(digits or 0))
            self._version = tuple(parts[:3]) or (0,)
        return self._version

    def login(self) -> None:
        if self.token:
            self.version()
            self.auth = self.token
            # 校验 token 是否可用（用需要权限的接口探一次）
            self.call("host.get", {"output": ["hostid"], "limit": 1})
            return
        if not self.user or not self.password:
            raise ZabbixError("未配置 Zabbix 账号密码或 API Token")
        self.version()
        result = self._post("user.login", {"username": self.user, "password": self.password}, auth="")
        if not result:
            raise ZabbixError("Zabbix 登录失败：用户名或密码错误")
        self.auth = result

    def call(self, method: str, params: Any = None) -> Any:
        return self._post(method, params or {})

    # ------------------------------------------------------------ 资源保障 --
    def ensure_group(self, name: str) -> str:
        result = self.call("hostgroup.get", {"filter": {"name": [name]}, "output": ["groupid", "name"]})
        if result:
            return str(result[0]["groupid"])
        created = self.call("hostgroup.create", {"name": name})
        return str(created["groupids"][0])

    def find_template(self, candidates: List[str], explicit: str = "") -> Tuple[str, str]:
        wanted = [explicit] if explicit else list(candidates)
        for name in wanted:
            if not name:
                continue
            result = self.call(
                "template.get",
                {"filter": {"name": [name]}, "output": ["templateid", "name"]},
            )
            if result:
                return str(result[0]["templateid"]), result[0]["name"]

        suggestions = self.call(
            "template.get",
            {"search": {"name": "H3C"}, "output": ["templateid", "name"], "limit": 15},
        ) or []
        hint = "、".join(item["name"] for item in suggestions) or "（未找到含 H3C 的模板，需先在 Zabbix 导入华三模板）"
        raise ZabbixError(f"未找到模板 {wanted}。可用候选: {hint}")

    def find_proxy(self, name: str) -> Optional[str]:
        if not name:
            return None
        result = self.call("proxy.get", {"filter": {"name": [name]}, "output": ["proxyid", "name"]})
        if not result:
            raise ZabbixError(f"未找到 Zabbix proxy: {name}")
        return str(result[0]["proxyid"])

    def get_host(self, name: str) -> Optional[Dict[str, Any]]:
        result = self.call("host.get", {
            "filter": {"host": [name]},
            "output": ["hostid", "host", "name", "status"],
            "selectGroups": ["groupid", "name"],
            "selectParentTemplates": ["templateid", "name"],
            "selectInterfaces": ["interfaceid", "type", "main", "ip", "dns", "port", "useip", "details"],
            "selectMacros": ["macro", "value"],
        })
        return result[0] if result else None


# ---------------------------------------------------------------- 计划 ----
@dataclass
class HostSpec:
    name: str
    ip: str
    community: str
    group_name: str = ""
    template_name: str = ""
    port: int = 161
    macro: str = "{$SNMP_COMMUNITY}"
    proxy_name: str = ""
    description: str = ""
    overwrite_interface: bool = False


@dataclass
class HostPlan:
    action: str
    changes: List[str] = field(default_factory=list)
    method: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    extra_calls: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)


def _snmp_interface(existing: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for interface in existing.get("interfaces") or []:
        if str(interface.get("type")) == "2":
            return interface
    return None


def plan_host(
    existing: Optional[Dict[str, Any]],
    spec: HostSpec,
    group_id: str,
    template_id: str,
    proxy_id: Optional[str] = None,
) -> HostPlan:
    """对比现状与目标，产出变更计划（纯函数，便于单测）。"""
    groups = [{"groupid": group_id}]
    templates = [{"templateid": template_id}]

    if not existing:
        params: Dict[str, Any] = {
            "host": spec.name,
            "name": spec.name,
            "status": 0,
            "groups": groups,
            "templates": templates,
            "interfaces": [{
                "type": 2, "main": 1, "useip": 1, "ip": spec.ip, "dns": "", "port": str(spec.port),
                "details": {"version": 2, "bulk": 1, "community": spec.macro},
            }],
            "macros": [{"macro": spec.macro, "value": spec.community}],
            "tags": [{"tag": "managed_by", "value": "h3c-ops-agent"}],
        }
        if proxy_id:
            params["proxyid"] = proxy_id
        if spec.description:
            params["description"] = spec.description
        return HostPlan(STATUS_OK, ["新建主机 + SNMP 接口 + 关联模板"], "host.create", params)

    changes: List[str] = []
    params = {"hostid": str(existing["hostid"])}

    existing_groups = {str(g["groupid"]) for g in existing.get("groups") or []}
    if group_id not in existing_groups:
        merged = [{"groupid": gid} for gid in existing_groups | {group_id}]
        params["groups"] = merged
        changes.append(f"补充主机组 {spec.group_name or group_id}")

    existing_templates = {str(t["templateid"]) for t in existing.get("parentTemplates") or []}
    if template_id not in existing_templates:
        params["templates"] = [{"templateid": tid} for tid in existing_templates | {template_id}]
        changes.append(f"关联模板 {spec.template_name or template_id}")

    interface = _snmp_interface(existing)
    extra_calls: List[Tuple[str, Dict[str, Any]]] = []
    if interface is None:
        extra_calls.append(("hostinterface.create", {
            "hostid": str(existing["hostid"]),
            "type": 2, "main": 1, "useip": 1, "ip": spec.ip, "dns": "", "port": str(spec.port),
            "details": {"version": 2, "bulk": 1, "community": spec.macro},
        }))
        changes.append("新增 SNMP 接口")
    else:
        current_ip = interface.get("ip") or ""
        if current_ip != spec.ip:
            if spec.overwrite_interface:
                extra_calls.append(("hostinterface.update", {
                    "interfaceid": str(interface["interfaceid"]),
                    "useip": 1, "ip": spec.ip, "dns": "", "port": str(spec.port),
                }))
                changes.append(f"SNMP 接口 IP {current_ip} → {spec.ip}")
            else:
                return HostPlan(
                    STATUS_CONFLICT,
                    [f"同名主机的 SNMP 接口 IP 是 {current_ip}，与清单 {spec.ip} 不一致（已跳过，确认后开 overwrite_interface）"],
                )
        elif str(interface.get("port") or "") != str(spec.port):
            extra_calls.append(("hostinterface.update", {
                "interfaceid": str(interface["interfaceid"]), "port": str(spec.port),
            }))
            changes.append(f"SNMP 端口 → {spec.port}")

    macros = {m["macro"]: m.get("value", "") for m in existing.get("macros") or []}
    if macros.get(spec.macro) != spec.community:
        merged_macros = [{"macro": key, "value": value} for key, value in macros.items() if key != spec.macro]
        merged_macros.append({"macro": spec.macro, "value": spec.community})
        params["macros"] = merged_macros
        changes.append(f"更新宏 {spec.macro}")

    if str(existing.get("status", "0")) != "0":
        params["status"] = 0
        changes.append("主机启用监控")

    if not changes:
        return HostPlan(STATUS_SKIP, [])
    return HostPlan(STATUS_OK, changes, "host.update", params, extra_calls)


@dataclass
class HostResult:
    status: str
    detail: str
    changes: List[str] = field(default_factory=list)
    hostid: str = ""
    dry_run: bool = False


def ensure_host(
    api: ZabbixAPI,
    spec: HostSpec,
    template_candidates: Optional[List[str]] = None,
    dry_run: bool = True,
) -> HostResult:
    """把一台设备接入 Zabbix（幂等）。"""
    group_id = api.ensure_group(spec.group_name) if spec.group_name else "0"
    explicit = spec.template_name
    template_id, template_real_name = api.find_template(list(template_candidates or []), explicit)
    spec.template_name = template_real_name
    proxy_id = api.find_proxy(spec.proxy_name)

    existing = api.get_host(spec.name)
    plan = plan_host(existing, spec, group_id, template_id, proxy_id)

    if plan.action == STATUS_CONFLICT:
        return HostResult(STATUS_CONFLICT, plan.changes[0])
    if plan.action == STATUS_SKIP:
        return HostResult(STATUS_SKIP, "主机已存在且配置一致，无需变更", [], str(existing["hostid"]))

    if dry_run:
        return HostResult(STATUS_DRY, f"将执行 {plan.method}：{'；'.join(plan.changes)}", plan.changes, "", True)

    try:
        if plan.method == "host.create":
            created = api.call("host.create", plan.params)
            hostid = str(created["hostids"][0])
        elif plan.method == "host.update":
            api.call("host.update", plan.params)
            hostid = str(existing["hostid"])
        else:
            hostid = str(existing["hostid"]) if existing else ""
        for method, params in plan.extra_calls:
            api.call(method, params)
    except ZabbixError as e:
        return HostResult(STATUS_FAIL, str(e))

    return HostResult(STATUS_OK, "；".join(plan.changes), plan.changes, hostid)
