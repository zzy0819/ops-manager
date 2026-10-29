#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置备份：抓取 running-config，落地版本快照，并与上一版做差异对比。

目录结构：
    backups/<设备名>/<时间戳>.cfg        每次快照
    backups/<设备名>/<时间戳>.diff       与上一版的 unified diff（有变化才写）
    backups/<设备名>/<时间戳>.meta.json  元信息（型号/版本/序列号）
    backups/<设备名>/latest.cfg          最新一份，便于快速对比与查看
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ssh import H3CSession, shorten

CMD_CURRENT_CONFIG = "display current-configuration"
STATUS_OK, STATUS_CHANGED, STATUS_FAIL = "成功", "有变更", "失败"

SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class BackupResult:
    status: str
    detail: str = ""
    path: str = ""
    changed: bool = False
    added: int = 0
    removed: int = 0
    diff_lines: List[str] = field(default_factory=list, repr=False)
    size: int = 0


def safe_name(hostname: str) -> str:
    name = SAFE_RE.sub("_", (hostname or "").strip()).strip("._")
    return name or "unknown"


def normalize_config(text: str) -> str:
    """去掉行尾空白与空行堆叠，保证 diff 不被格式差异干扰。"""
    lines = [line.rstrip() for line in (text or "").replace("\r\n", "\n").split("\n")]
    out: List[str] = []
    blank = False
    for line in lines:
        if not line:
            if blank:
                continue
            blank = True
            out.append("")
        else:
            blank = False
            out.append(line)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out) + ("\n" if out else "")


def diff_configs(old: str, new: str, old_label: str = "previous", new_label: str = "current") -> Dict[str, Any]:
    old_lines = normalize_config(old).splitlines()
    new_lines = normalize_config(new).splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=old_label, tofile=new_label, lineterm="", n=2))
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    return {"changed": bool(added or removed), "added": added, "removed": removed, "diff": diff}


def resolve_dir(cfg, hostname: str) -> Path:
    base = Path(cfg.get("global.backup_dir", "backups"))
    base = base if base.is_absolute() else cfg.base_dir / base
    return base / safe_name(hostname)


def prune(directory: Path, keep: int) -> List[Path]:
    """只保留最近 keep 份 .cfg，连带清理同名 .diff / .meta.json。"""
    snapshots = sorted(
        (p for p in directory.glob("*.cfg") if p.name != "latest.cfg"),
        key=lambda p: p.name, reverse=True,
    )
    removed: List[Path] = []
    for stale in snapshots[keep:]:
        for suffix in (".cfg", ".diff", ".meta.json"):
            candidate = stale.with_suffix(suffix)
            if candidate.exists():
                try:
                    candidate.unlink()
                    removed.append(candidate)
                except OSError:
                    pass
    return removed


def backup(
    session: H3CSession,
    cfg,
    device_label: str = "",
    meta: Optional[Dict[str, Any]] = None,
    timeout: int = 120,
) -> BackupResult:
    """抓取并保存一份配置快照。"""
    hostname = session.hostname or device_label or session.ip

    if cfg.get("backup.save_before_backup", True):
        save_result = session.save()
        if not save_result.ok:
            return BackupResult(STATUS_FAIL, f"备份前 save 失败: {save_result.detail}")

    output, error = session.send_safe(CMD_CURRENT_CONFIG, timeout=timeout)
    if error or not output.strip():
        return BackupResult(STATUS_FAIL, f"抓取配置失败: {error or '回显为空'}")
    if "unrecognized command" in output.lower():
        return BackupResult(STATUS_FAIL, "设备不支持 display current-configuration")

    content = normalize_config(output)
    directory = resolve_dir(cfg, hostname)
    directory.mkdir(parents=True, exist_ok=True)

    latest = directory / "latest.cfg"
    previous = latest.read_text(encoding="utf-8", errors="ignore") if latest.exists() else ""
    comparison = diff_configs(previous, content, "previous(latest)", "current")

    base_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stamp = base_stamp
    snapshot = directory / f"{stamp}.cfg"
    counter = 1
    while snapshot.exists():  # 同一秒内多次备份不互相覆盖
        stamp = f"{base_stamp}_{counter}"
        snapshot = directory / f"{stamp}.cfg"
        counter += 1
    snapshot.write_text(content, encoding="utf-8")
    latest.write_text(content, encoding="utf-8")

    payload = dict(meta or {})
    payload.setdefault("hostname", hostname)
    payload.setdefault("captured_at", datetime.now().isoformat(timespec="seconds"))
    payload["changed"] = comparison["changed"]
    payload["added_lines"] = comparison["added"]
    payload["removed_lines"] = comparison["removed"]
    payload["sha"] = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    (directory / f"{stamp}.meta.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if previous and comparison["changed"]:
        header = [
            f"# {hostname} 配置变更 {stamp}",
            f"# 新增 {comparison['added']} 行，删除 {comparison['removed']} 行",
            "",
        ]
        (directory / f"{stamp}.diff").write_text(
            "\n".join(header + comparison["diff"]) + "\n", encoding="utf-8"
        )

    prune(directory, int(cfg.get("backup.keep", 30) or 30))

    if not previous:
        return BackupResult(
            STATUS_OK, f"首次备份完成（{len(content.splitlines())} 行）",
            str(snapshot), False, 0, 0, [], len(content),
        )
    if comparison["changed"]:
        return BackupResult(
            STATUS_CHANGED,
            f"配置有变更：+{comparison['added']} / -{comparison['removed']} 行（详见同目录 .diff）",
            str(snapshot), True, comparison["added"], comparison["removed"],
            comparison["diff"][:400], len(content),
        )
    return BackupResult(STATUS_OK, "与上次备份一致", str(snapshot), False, 0, 0, [], len(content))


def latest_config(cfg, hostname: str) -> str:
    path = resolve_dir(cfg, hostname) / "latest.cfg"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def list_snapshots(cfg, hostname: str) -> List[Dict[str, Any]]:
    directory = resolve_dir(cfg, hostname)
    if not directory.exists():
        return []
    items = []
    for path in sorted(
        (p for p in directory.glob("*.cfg") if p.name != "latest.cfg"),
        key=lambda p: p.name, reverse=True,
    ):
        meta_path = path.with_suffix(".meta.json")
        meta: Dict[str, Any] = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
        items.append({
            "time": path.stem,
            "size": path.stat().st_size,
            "changed": meta.get("changed"),
            "added": meta.get("added_lines"),
            "removed": meta.get("removed_lines"),
        })
    return items


def short_detail(text: str, limit: int = 120) -> str:
    return shorten(text, limit)
