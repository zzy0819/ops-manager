#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结果数据模型（report / runner 共用）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .backup import BackupResult
from .inspect import Inspection
from .inventory import Device

STAGE_NAMES = {
    "inspect": "巡检",
    "snmp": "团体名",
    "zabbix": "Zabbix接入",
    "backup": "配置备份",
}


@dataclass
class Stage:
    name: str
    status: str = "未执行"
    detail: str = ""
    warnings: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"成功", "有变更", "无变化", "跳过", "预览"}

    @property
    def is_problem(self) -> bool:
        return self.status in {"失败", "冲突"}


@dataclass
class DeviceResult:
    dev: Device
    reachable: bool = False
    error: str = ""
    inspection: Optional[Inspection] = None
    snmp: Optional[Stage] = None
    zabbix: Optional[Stage] = None
    backup: Optional[BackupResult] = None
    elapsed: float = 0.0
    login_account: str = ""       # 实际登录成功的账号（多凭据回落后可能不是清单里的）
    login_note: str = ""          # 提权情况说明
    warnings: List[str] = field(default_factory=list)  # 登录/提权阶段的告警

    @property
    def label(self) -> str:
        if self.inspection and self.inspection.hostname:
            return self.inspection.hostname
        return self.dev.label

    @property
    def level(self) -> str:
        if not self.reachable:
            return "不可达"
        return self.inspection.level if self.inspection else "未知"

    @property
    def score(self) -> int:
        return self.inspection.score if self.inspection else 0

    def problems(self) -> List[str]:
        items = []
        if not self.reachable:
            items.append(self.error or "无法登录")
        if self.inspection:
            items.extend(i.detail for i in self.inspection.issues if i.level in ("严重", "警告"))
        for stage in (self.snmp, self.zabbix):
            if stage and stage.is_problem:
                items.append(f"{stage.name}: {stage.detail}")
        return items

    def all_stages(self) -> List[Stage]:
        out: List[Stage] = []
        if self.snmp:
            out.append(self.snmp)
        if self.zabbix:
            out.append(self.zabbix)
        if self.backup:
            out.append(Stage("配置备份", self.backup.status, self.backup.detail))
        return out
