#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量调度：并发 SSH 阶段 → 串行 Zabbix 接入 → 汇总报告。"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from . import backup as backup_mod
from . import inspect as inspect_mod
from . import report as report_mod
from . import snmp as snmp_mod
from .inventory import Device
from .models import DeviceResult, Stage
from .ssh import AuthError, ConnectError, H3CError, H3CSession
from .zabbix import HostSpec, ZabbixAPI, ZabbixError, ensure_host

log = logging.getLogger("h3c_ops.runner")

ALL_STAGES = ("inspect", "snmp", "zabbix", "backup")


class RunnerError(Exception):
    pass


def prepare_run_dir(cfg) -> Path:
    base = Path(cfg.get("global.run_dir", "runs"))
    base = base if base.is_absolute() else cfg.base_dir / base
    run_dir = base / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _session(cfg, device: Device) -> H3CSession:
    return H3CSession(
        ip=device.ip,
        username=device.username,
        password=device.password,
        port=device.port,
        secret=device.secret,
        connect_timeout=int(cfg.get("global.connect_timeout", 15)),
        command_timeout=int(cfg.get("global.command_timeout", 30)),
        save_timeout=int(cfg.get("global.save_timeout", 180)),
    )


def process_device(cfg, device: Device, stages: Sequence[str], dry_run: bool) -> DeviceResult:
    """单台设备：一次登录跑完所有需要 SSH 的阶段。"""
    result = DeviceResult(dev=device)
    started = time.time()
    session = _session(cfg, device)

    try:
        session.connect()
        result.reachable = True
    except (AuthError, ConnectError, H3CError) as e:
        result.error = str(e)
        result.elapsed = round(time.time() - started, 1)
        if "snmp" in stages:
            result.snmp = Stage("团体名", "失败", "设备不可达，已跳过")
        if "zabbix" in stages:
            result.zabbix = Stage("Zabbix接入", "失败", "设备不可达，已跳过")
        if "backup" in stages:
            result.backup = backup_mod.BackupResult(backup_mod.STATUS_FAIL, "设备不可达，已跳过")
        return result

    try:
        if "inspect" in stages:
            try:
                last_config = backup_mod.latest_config(cfg, session.hostname)
                result.inspection = inspect_mod.collect(
                    session,
                    thresholds=cfg.section("inspect").get("thresholds", {}),
                    collect_optical=bool(cfg.get("inspect.collect_optical", False)),
                    last_config=last_config,
                )
                log.info("[巡检] %s(%s) 健康分 %s / %s", session.hostname, device.ip,
                         result.inspection.score, result.inspection.level)
            except H3CError as e:
                log.error("[巡检] %s(%s) 失败: %s", session.hostname, device.ip, e)

        if "snmp" in stages:
            try:
                outcome = snmp_mod.apply(
                    session, cfg.section("snmp"), device.community, dry_run=dry_run
                )
                result.snmp = Stage("团体名", outcome.status, outcome.detail, outcome.warnings,
                                    {"acl": outcome.acl, "verified": outcome.verified})
                level = logging.ERROR if outcome.status == "失败" else logging.INFO
                log.log(level, "[团体名] %s(%s) %s - %s", session.hostname, device.ip,
                        outcome.status, outcome.detail)
            except H3CError as e:
                result.snmp = Stage("团体名", "失败", str(e))
                log.error("[团体名] %s(%s) 失败: %s", session.hostname, device.ip, e)

        if "backup" in stages:
            try:
                meta = {
                    "ip": device.ip,
                    "group": device.group,
                    "model": result.inspection.model if result.inspection else "",
                }
                outcome = backup_mod.backup(session, cfg, device_label=device.label, meta=meta)
                result.backup = outcome
                level = logging.ERROR if outcome.status == "失败" else logging.INFO
                log.log(level, "[备份] %s(%s) %s - %s", session.hostname, device.ip,
                        outcome.status, outcome.detail)
            except H3CError as e:
                result.backup = backup_mod.BackupResult(backup_mod.STATUS_FAIL, str(e))
                log.error("[备份] %s(%s) 失败: %s", session.hostname, device.ip, e)
    finally:
        session.close()
        result.elapsed = round(time.time() - started, 1)
    return result


def run_stage_zabbix(
    cfg,
    results: List[DeviceResult],
    dry_run: bool,
) -> None:
    """串行把可达设备接入 Zabbix。"""
    section = cfg.section("zabbix")
    try:
        api = ZabbixAPI(
            url=section.get("url", ""),
            user=section.get("user", ""),
            password=section.get("password", ""),
            token=section.get("api_token", ""),
            verify_tls=bool(section.get("verify_tls", True)),
        )
        api.login()
    except ZabbixError as e:
        for result in results:
            if result.zabbix is None:
                result.zabbix = Stage("Zabbix接入", "失败", f"无法连接 Zabbix: {e}")
        log.error("Zabbix 登录失败: %s", e)
        return

    candidates = section.get("template_candidates") or []
    name_source = section.get("host_name_source", "sysname")
    for result in results:
        if not result.reachable:
            continue
        if result.inspection and result.inspection.hostname and name_source == "sysname":
            host_name = result.inspection.hostname
        else:
            host_name = result.dev.name or result.dev.ip

        community = result.dev.community or cfg.get("snmp.read_community", "")
        spec = HostSpec(
            name=host_name,
            ip=result.dev.ip,
            community=community,
            group_name=result.dev.group or section.get("host_group", ""),
            template_name=result.dev.template,
            port=int(section.get("snmp_port", 161) or 161),
            macro=section.get("community_macro", "{$SNMP_COMMUNITY}"),
            proxy_name=section.get("proxy_name", ""),
            description=f"{result.inspection.model if result.inspection else 'H3C'} | {result.dev.ip} | managed by h3c-ops-agent",
            overwrite_interface=bool(section.get("overwrite_interface", False)),
        )
        try:
            outcome = ensure_host(api, spec, candidates, dry_run=dry_run)
        except ZabbixError as e:
            outcome = None
            result.zabbix = Stage("Zabbix接入", "失败", str(e))
            log.error("[Zabbix] %s 失败: %s", host_name, e)
            continue

        result.zabbix = Stage(
            "Zabbix接入", outcome.status, outcome.detail, [], {"hostid": outcome.hostid}
        )
        log.info("[Zabbix] %s(%s) %s - %s", host_name, result.dev.ip, outcome.status, outcome.detail)


def execute(
    cfg,
    devices: List[Device],
    stages: Sequence[str],
    dry_run: bool,
    run_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """跑完整流程，返回 {results, run_dir, files, meta}。"""
    stages = [s for s in stages if s in ALL_STAGES]
    if not stages:
        raise RunnerError("未选择任何执行阶段")

    run_dir = run_dir or prepare_run_dir(cfg)
    started_at = datetime.now()
    workers = int(cfg.get("global.concurrency", 8) or 8)
    ssh_stages = [s for s in stages if s != "zabbix"]

    log.info("开始执行：设备 %d 台，阶段 %s，模式 %s，并发 %d",
             len(devices), "→".join(stages), "预览（不改设备）" if dry_run else "实际执行", workers)

    results: List[DeviceResult] = []
    if ssh_stages:
        pool = ThreadPoolExecutor(max_workers=min(workers, max(1, len(devices))))
        futures = {pool.submit(process_device, cfg, dev, stages, dry_run): dev for dev in devices}
        try:
            for future in as_completed(futures):
                device = futures[future]
                try:
                    results.append(future.result())
                except Exception as e:  # noqa: BLE001
                    log.exception("设备 %s 处理异常", device.ip)
                    results.append(DeviceResult(dev=device, error=f"{type(e).__name__}: {e}"))
        except KeyboardInterrupt:
            log.warning("收到中断，取消未开始的任务…")
            pool.shutdown(wait=True, cancel_futures=True)
            raise
        finally:
            pool.shutdown(wait=True)
        results.sort(key=lambda r: r.dev.row)
    else:
        results = [DeviceResult(dev=dev, reachable=True) for dev in devices]

    if "zabbix" in stages:
        run_stage_zabbix(cfg, results, dry_run)

    finished_at = datetime.now()
    meta: Dict[str, Any] = {
        "started_at": started_at.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": finished_at.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "预览（未变更设备）" if dry_run else "实际执行",
        "stages": [s for s in ("巡检", "团体名", "Zabbix接入", "配置备份") if _stage_key(s) in stages],
        "config_file": str(cfg.path or ""),
        "inventory_file": str(cfg.get("inventory_file", "")),
        "zabbix_url": cfg.get("zabbix.url", "-"),
    }

    xlsx_path = report_mod.write_xlsx(results, run_dir / "report.xlsx", meta)
    md_path = report_mod.write_markdown(results, run_dir / "summary.md", meta)
    json_path = run_dir / "results.json"
    json_path.write_text(
        json.dumps([_serialize(r) for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "results": results,
        "run_dir": run_dir,
        "files": {"xlsx": str(xlsx_path), "markdown": str(md_path), "json": str(json_path)},
        "meta": meta,
    }


def _stage_key(label: str) -> str:
    return {"巡检": "inspect", "团体名": "snmp", "Zabbix接入": "zabbix", "配置备份": "backup"}.get(label, "")


def _serialize(result: DeviceResult) -> Dict[str, Any]:
    insp = result.inspection
    return {
        "device": result.dev.label,
        "ip": result.dev.ip,
        "reachable": result.reachable,
        "error": result.error,
        "level": result.level,
        "score": result.score,
        "model": insp.model if insp else "",
        "issues": [{"level": i.level, "item": i.item, "detail": i.detail} for i in (insp.issues if insp else [])],
        "snmp": result.snmp.status if result.snmp else "",
        "zabbix": result.zabbix.status if result.zabbix else "",
        "backup": {
            "status": result.backup.status,
            "path": result.backup.path,
            "changed": result.backup.changed,
            "added": result.backup.added,
            "removed": result.backup.removed,
        } if result.backup else None,
        "elapsed": result.elapsed,
    }
