#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""巡检：命令采集 + 回显解析 + 健康判定。

所有 parse_* 都是纯函数，方便单测（不依赖真实设备）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import snmp as snmp_mod
from .ssh import H3CSession, shorten

# ---------------------------------------------------------------- 命令集 ----
CMD_VERSION = "display version"
CMD_MANUINFO = "display device manuinfo"
CMD_CPU = "display cpu-usage"
CMD_MEMORY = "display memory"
CMD_ENVIRONMENT = "display environment"
CMD_POWER = "display power"
CMD_FAN = "display fan"
CMD_INTERFACE_BRIEF = "display interface brief"
CMD_SNMP_CONF = "display current-configuration | include snmp-agent"
CMD_OPTICAL = "display transceiver diagnosis interface"

LEVEL_CRITICAL, LEVEL_WARNING, LEVEL_INFO = "严重", "警告", "提示"

# 物理端口前缀（用于判断"端口 down"是否有意义）
PHYSICAL_PREFIX = re.compile(
    r"^(?:GE|XGE|FGE|HGE|WGE|SGE|TGE|"
    r"GigabitEthernet|Ten-GigabitEthernet|FortyGigE|HundredGigE|Twenty-FiveGigE|"
    r"Twenty-FiveGigE|M-GigabitEthernet|Ethernet|Eth)\d"
)
LOGICAL_PREFIX = re.compile(
    r"^(?:Vlan|BAGG|RAGG|Bridge-Aggregation|Route-Aggregation|NULL|Loop|REG|Tun|InLoop)"
)
LINK_STATES = {"UP", "DOWN", "ADM", "STBY", "*DOWN", "(DL)", "(LD)"}


@dataclass
class Issue:
    level: str
    item: str
    detail: str


@dataclass
class Inspection:
    """单台设备的巡检结果。"""

    hostname: str = ""
    model: str = ""
    comware: str = ""
    release: str = ""
    uptime: str = ""
    uptime_days: Optional[float] = None
    serial: str = ""
    mac: str = ""
    vendor: str = ""
    manu_date: str = ""

    cpu: Optional[int] = None
    mem_percent: Optional[float] = None
    mem_total_kb: Optional[int] = None
    mem_used_kb: Optional[int] = None
    max_temp: Optional[float] = None
    temp_sensor: str = ""
    fan_total: int = 0
    fan_bad: List[str] = field(default_factory=list)
    power_total: int = 0
    power_bad: List[str] = field(default_factory=list)

    if_total: int = 0
    if_up: int = 0
    if_down: int = 0
    if_admin_down: int = 0
    down_ports: List[str] = field(default_factory=list)

    snmp: Dict[str, Any] = field(default_factory=dict)
    optical_bad: List[str] = field(default_factory=list)

    issues: List[Issue] = field(default_factory=list)
    score: int = 100
    level: str = "正常"

    failed: Dict[str, str] = field(default_factory=dict)   # 采集失败的命令
    raw: Dict[str, str] = field(default_factory=dict, repr=False)

    def summary(self) -> str:
        parts = []
        if self.model:
            parts.append(self.model)
        if self.cpu is not None:
            parts.append(f"CPU {self.cpu}%")
        if self.mem_percent is not None:
            parts.append(f"内存 {self.mem_percent:.0f}%")
        if self.max_temp is not None:
            parts.append(f"{self.max_temp:.0f}℃")
        if self.if_total:
            parts.append(f"端口 {self.if_up}/{self.if_total} up")
        return " · ".join(parts)


# ---------------------------------------------------------------- 解析器 ----
def parse_uptime_days(text: str) -> Optional[float]:
    days = 0.0
    matched = False
    for value, unit in re.findall(r"(\d+)\s*(week|day|hour|minute)s?", text, re.IGNORECASE):
        matched = True
        number = int(value)
        unit = unit.lower()
        if unit == "week":
            days += number * 7
        elif unit == "day":
            days += number
        elif unit == "hour":
            days += number / 24
        else:
            days += number / 1440
    return round(days, 2) if matched else None


def parse_version(text: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    match = re.search(r"Comware\s+Software,\s*Version\s+([\d.]+)\s*,\s*Release\s+(\S+)", text, re.I)
    if match:
        info["comware"] = match.group(1)
        info["release"] = match.group(2)

    match = re.search(r"^H3C\s+([A-Za-z0-9][\w./-]*)\s+uptime is\s+(.+)$", text, re.I | re.M)
    if match:
        info["model"] = match.group(1)
        info["uptime"] = match.group(2).strip()
        days = parse_uptime_days(info["uptime"])
        if days is not None:
            info["uptime_days"] = days
    else:
        match = re.search(r"^H3C\s+([A-Za-z0-9][\w./-]*)\s*$", text, re.I | re.M)
        if match:
            info["model"] = match.group(1)

    # 堆叠设备多 slot，取第一台型号即可
    if not info.get("model"):
        match = re.search(r"H3C\s+(S\d[\w./-]+)", text)
        if match:
            info["model"] = match.group(1)
    return info


def parse_manuinfo(text: str) -> Dict[str, str]:
    info: Dict[str, str] = {}
    mapping = {
        "DEVICE_NAME": "model",
        "DEVICE_SERIAL_NUMBER": "serial",
        "MAC_ADDRESS": "mac",
        "MANUFACTURING_DATE": "manu_date",
        "VENDOR_NAME": "vendor",
    }
    for key, value in re.findall(r"^\s*([A-Z_]+)\s*:\s*(.+?)\s*$", text, re.M):
        if key in mapping:
            info[mapping[key]] = value
    return info


def parse_cpu(text: str) -> Optional[int]:
    """优先取 5 分钟平均值，多 slot 取最大值。"""
    for pattern in (
        r"(\d+)%\s+in last 5 minutes",
        r"(\d+)%\s+in last 1 minute",
        r"5\s*minutes?\s*[:=]\s*(\d+)%",
        r"CPU usage[^0-9]{0,20}(\d+)%",
        r"CPU utilization[^0-9]{0,20}(\d+)%",
    ):
        values = [int(v) for v in re.findall(pattern, text, re.I)]
        if values:
            return max(values)
    return None


def parse_memory(text: str) -> Dict[str, Optional[float]]:
    """返回 total_kb / used_kb / percent。"""
    result: Dict[str, Optional[float]] = {"total_kb": None, "used_kb": None, "percent": None}

    match = re.search(r"^\s*Mem:\s+(\d+)\s+(\d+)\s+(\d+)", text, re.M)
    if match:
        total, used = int(match.group(1)), int(match.group(2))
        if total:
            result.update(total_kb=total, used_kb=used, percent=round(used * 100 / total, 1))
            return result

    match = re.search(r"Total\s+Used\s+Free", text)
    if match:  # 逐行表格形式
        for line in text[match.end():].splitlines():
            numbers = re.findall(r"(\d+)", line)
            if len(numbers) >= 2 and line.strip().startswith("Mem"):
                total, used = int(numbers[0]), int(numbers[1])
                if total:
                    result.update(total_kb=total, used_kb=used, percent=round(used * 100 / total, 1))
                    return result

    match = re.search(r"Used Rate\s*[:：]\s*(\d+)%", text, re.I)
    if match:
        result["percent"] = float(match.group(1))
        return result

    match = re.search(r"Total Memory[^:]*:\s*(\d+)", text, re.I)
    if match:
        result["total_kb"] = int(match.group(1))
        match = re.search(r"Used Memory[^:]*:\s*(\d+)", text, re.I)
        if match:
            used = int(match.group(1))
            total = result["total_kb"] or 0
            result["used_kb"] = used
            if total:
                result["percent"] = round(used * 100 / total, 1)
    return result


def parse_environment(text: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {"max_temp": None, "sensor": "", "sensors": {}}
    if not text or "unrecognized" in text.lower():
        return info

    match = re.search(r"System Temperature\s*[:：]\s*(\d+)", text, re.I)
    if match:
        info["max_temp"] = float(match.group(1))
        return info

    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) < 2:
            continue
        if tokens[0].lower() in {"sensor", "system", "----"} or line.strip().startswith("-"):
            continue
        numbers = [t for t in tokens[1:] if re.fullmatch(r"-?\d+", t)]
        if not numbers:
            continue
        try:
            value = float(numbers[0])
        except ValueError:
            continue
        info["sensors"][tokens[0]] = value
        if info["max_temp"] is None or value > info["max_temp"]:
            info["max_temp"] = value
            info["sensor"] = tokens[0]
    return info


def _parse_state_table(text: str, keyword: str) -> Tuple[int, List[str]]:
    """解析 display power / display fan 这类 'ID State' 表格。"""
    total = 0
    bad: List[str] = []
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("-"):
            continue
        lowered = line.lower()
        if keyword in lowered and "state" in lowered:
            continue  # 表头

        single = re.search(rf"{keyword}\s*(\d+)\s*(?:state)?\s*[:：]\s*(\w+)", line, re.I)
        if single:
            total += 1
            state = single.group(2)
            if state.lower() not in {"normal", "ok", "absent"}:
                bad.append(f"{keyword}{single.group(1)}({state})")
            continue

        tokens = line.split()
        if len(tokens) >= 2 and re.fullmatch(r"\d+", tokens[0]):
            total += 1
            state = tokens[1]
            if state.lower() not in {"normal", "ok", "absent"}:
                bad.append(f"{keyword}{tokens[0]}({state})")
    return total, bad


def parse_power(text: str) -> Tuple[int, List[str]]:
    if not text or "unrecognized" in text.lower():
        return 0, []
    return _parse_state_table(text, "Power")


def parse_fan(text: str) -> Tuple[int, List[str]]:
    if not text or "unrecognized" in text.lower():
        return 0, []
    return _parse_state_table(text, "Fan")


IFACE_RE = re.compile(
    r"^(?:GE|XGE|FGE|HGE|WGE|SGE|TGE|"
    r"GigabitEthernet|Ten-GigabitEthernet|FortyGigE|HundredGigE|Twenty-FiveGigE|"
    r"M-GigabitEthernet|Ethernet|Eth|Vlan|BAGG|RAGG|Bridge-Aggregation|"
    r"Route-Aggregation|NULL|REG|Loop|Tun)"
)


def parse_interfaces(text: str) -> Dict[str, Any]:
    """解析 display interface brief，按接口名去重（route/bridge 两段会重复）。"""
    seen: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-"):
            continue
        if stripped.startswith(("Link:", "Protocol:", "Speed:", "Duplex:", "Type:", "Brief")):
            continue
        tokens = stripped.split()
        if len(tokens) < 2:
            continue
        name, state = tokens[0], tokens[1].upper()
        if not IFACE_RE.match(name) or name.lower() == "interface":
            continue
        if state not in LINK_STATES and not state.startswith("*"):
            continue
        if name not in seen or seen[name] != "UP":
            seen[name] = state

    stats = {
        "total": 0, "up": 0, "down": 0, "admin_down": 0,
        "down_ports": [], "physical_total": 0,
    }
    for name, state in seen.items():
        stats["total"] += 1
        is_physical = bool(PHYSICAL_PREFIX.match(name))
        if is_physical:
            stats["physical_total"] += 1
        if state == "UP":
            stats["up"] += 1
        elif state in ("ADM", "(DL)", "(LD)"):
            stats["admin_down"] += 1
        else:
            stats["down"] += 1
            if is_physical:
                stats["down_ports"].append(name)
    return stats


def parse_optical(text: str) -> List[str]:
    """返回收光功率异常（< -20dBm 或 N/A）的端口列表。"""
    bad: List[str] = []
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if IFACE_RE.match(stripped) and len(stripped.split()) == 1:
            current = stripped
            continue
        match = re.search(r"RX\s*power\s*\(dBm\)\s*[:：]\s*(-?[\d.]+|N/?A)", stripped, re.I)
        if match and current:
            value = match.group(1)
            if value.upper().startswith("N"):
                bad.append(f"{current}(无收光)")
            else:
                try:
                    if float(value) < -20:
                        bad.append(f"{current}({value}dBm)")
                except ValueError:
                    pass
    return bad


# ---------------------------------------------------------------- 采集 ----
def collect(
    session: H3CSession,
    thresholds: Dict[str, Any],
    collect_optical: bool = False,
    last_config: str = "",
) -> Inspection:
    """在已登录的会话上跑一轮巡检。单条命令失败不影响其它项。"""
    insp = Inspection(hostname=session.hostname)
    command_timeout = getattr(session, "command_timeout", 30)

    def run(command: str, timeout: Optional[float] = None, optional: bool = False) -> str:
        """optional=True 用于风扇/电源/温度这类"部分型号不支持"的命令，失败不记异常。"""
        output, error = session.send_safe(command, timeout=timeout or command_timeout)
        if error:
            if not optional:
                insp.failed[command] = shorten(error, 160)
            return ""
        insp.raw[command] = output
        return output

    version = run(CMD_VERSION, timeout=40)
    version_info = parse_version(version)
    insp.model = version_info.get("model", "")
    insp.comware = version_info.get("comware", "")
    insp.release = version_info.get("release", "")
    insp.uptime = version_info.get("uptime", "")
    insp.uptime_days = version_info.get("uptime_days")

    manu = parse_manuinfo(run(CMD_MANUINFO, timeout=25))
    insp.serial = manu.get("serial", "")
    insp.mac = manu.get("mac", "")
    insp.vendor = manu.get("vendor", "")
    insp.manu_date = manu.get("manu_date", "")
    insp.model = insp.model or manu.get("model", "")

    insp.cpu = parse_cpu(run(CMD_CPU))
    memory = parse_memory(run(CMD_MEMORY))
    insp.mem_percent = memory.get("percent")
    insp.mem_total_kb = int(memory["total_kb"]) if memory.get("total_kb") else None
    insp.mem_used_kb = int(memory["used_kb"]) if memory.get("used_kb") else None

    environment = parse_environment(run(CMD_ENVIRONMENT, optional=True))
    insp.max_temp = environment.get("max_temp")
    insp.temp_sensor = environment.get("sensor", "")

    insp.fan_total, insp.fan_bad = parse_fan(run(CMD_FAN, optional=True))
    insp.power_total, insp.power_bad = parse_power(run(CMD_POWER, optional=True))

    interfaces = parse_interfaces(run(CMD_INTERFACE_BRIEF, timeout=45))
    insp.if_total = interfaces["total"]
    insp.if_up = interfaces["up"]
    insp.if_down = interfaces["down"]
    insp.if_admin_down = interfaces["admin_down"]
    insp.down_ports = interfaces["down_ports"]

    if collect_optical:
        insp.optical_bad = parse_optical(run(CMD_OPTICAL, timeout=90, optional=True))

    snmp_config = run(CMD_SNMP_CONF)
    insp.snmp = snmp_mod.parse_config_state(snmp_config)

    evaluate(insp, thresholds, last_config)
    return insp


def evaluate(insp: Inspection, thresholds: Dict[str, Any], last_config: str = "") -> None:
    """填充 issues / score / level。"""
    issues: List[Issue] = []

    cpu_limit = int(thresholds.get("cpu_percent", 80))
    if insp.cpu is None:
        issues.append(Issue(LEVEL_INFO, "CPU", "未能采集到 CPU 利用率"))
    elif insp.cpu > cpu_limit:
        level = LEVEL_CRITICAL if insp.cpu > cpu_limit + 10 else LEVEL_WARNING
        issues.append(Issue(level, "CPU", f"{insp.cpu}% 超过阈值 {cpu_limit}%"))

    mem_limit = int(thresholds.get("memory_percent", 85))
    if insp.mem_percent is None:
        issues.append(Issue(LEVEL_INFO, "内存", "未能采集到内存利用率"))
    elif insp.mem_percent > mem_limit:
        level = LEVEL_CRITICAL if insp.mem_percent > mem_limit + 8 else LEVEL_WARNING
        issues.append(Issue(level, "内存", f"{insp.mem_percent:.1f}% 超过阈值 {mem_limit}%"))

    temp_limit = int(thresholds.get("temperature", 60))
    if insp.max_temp is not None and insp.max_temp > temp_limit:
        level = LEVEL_CRITICAL if insp.max_temp > temp_limit + 10 else LEVEL_WARNING
        sensor = f"（{insp.temp_sensor}）" if insp.temp_sensor else ""
        issues.append(Issue(level, "温度", f"最高 {insp.max_temp:.0f}℃{sensor} 超过阈值 {temp_limit}℃"))

    if insp.fan_bad:
        issues.append(Issue(LEVEL_CRITICAL, "风扇", "异常: " + "、".join(insp.fan_bad[:5])))
    if insp.power_bad:
        issues.append(Issue(LEVEL_CRITICAL, "电源", "异常: " + "、".join(insp.power_bad[:5])))

    down_limit = int(thresholds.get("down_port_count", 0))
    if len(insp.down_ports) > down_limit:
        shown = "、".join(insp.down_ports[:8]) + ("…" if len(insp.down_ports) > 8 else "")
        issues.append(Issue(LEVEL_WARNING, "端口", f"{len(insp.down_ports)} 个物理口 down: {shown}"))

    if insp.uptime_days is not None and insp.uptime_days < 1:
        issues.append(Issue(LEVEL_INFO, "运行时长", f"设备近期重启（已运行 {insp.uptime}）"))

    if insp.optical_bad:
        issues.append(Issue(LEVEL_WARNING, "光模块", "收光异常: " + "、".join(insp.optical_bad[:6])))

    snmp_state = insp.snmp or {}
    if not snmp_state.get("has_snmp"):
        issues.append(Issue(LEVEL_WARNING, "SNMP", "未配置 snmp-agent，无法被监控平台采集"))
    elif not snmp_state.get("v2c"):
        issues.append(Issue(LEVEL_INFO, "SNMP", "未启用 v2c（当前可能只有 v3）"))

    for command, error in insp.failed.items():
        issues.append(Issue(LEVEL_INFO, "采集", f"{command} 执行失败: {shorten(error, 80)}"))

    insp.issues = issues
    penalty = {LEVEL_CRITICAL: 25, LEVEL_WARNING: 8, LEVEL_INFO: 2}
    score = 100 - sum(penalty.get(issue.level, 0) for issue in issues)
    insp.score = max(0, min(100, score))
    if any(issue.level == LEVEL_CRITICAL for issue in issues) or insp.score < 60:
        insp.level = "严重"
    elif insp.score < 75:
        insp.level = "警告"
    elif insp.score < 90 or any(issue.level == LEVEL_WARNING for issue in issues):
        insp.level = "关注"
    else:
        insp.level = "正常"
