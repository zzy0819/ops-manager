#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令行入口。"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path
from typing import List

from . import runner
from .config import ConfigError, load_config
from .inventory import read_inventory, write_template
from .login import Credential
from .report import console_summary

log = logging.getLogger("h3c_ops")

STAGE_CHOICES = {
    "inspect": ["inspect"],
    "snmp": ["snmp"],
    "zabbix": ["zabbix"],
    "backup": ["backup"],
    "full": ["inspect", "snmp", "zabbix", "backup"],
}


def setup_logging(verbose: bool, log_file: Path | None = None) -> None:
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="h3c-ops-agent",
        description="华三交换机批量巡检 / 标准团体名 / Zabbix 接入 / 配置备份",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python run.py init                                   生成 config.json 与 devices.xlsx
  python run.py devices                                检查清单能否正确解析（含凭据来源）
  python run.py snmp                                   预览团体名配置（只读，不改设备）
  python run.py snmp --apply -y                        按清单账号密码批量登录并下发团体名
  python run.py snmp --apply -y --limit 1              先拿一台试水
  python run.py snmp --apply -y --user admin --password xxx   临时改用指定账号
  python run.py inspect                                批量巡检（只读）
  python run.py full --apply                           巡检 + 团体名 + Zabbix + 备份
""",
    )
    parser.add_argument("command", nargs="?", default="full", choices=list(STAGE_CHOICES) + ["devices", "init"])
    parser.add_argument("-c", "--config", default="config.json", help="配置文件路径，默认 config.json")
    parser.add_argument("-f", "--inventory", help="设备清单路径，覆盖配置里的 inventory_file")
    parser.add_argument("-w", "--workers", type=int, help="并发数，默认取配置")
    parser.add_argument("--apply", action="store_true", help="实际执行写操作（默认只预览，不改设备）")
    parser.add_argument("-y", "--yes", action="store_true", help="跳过交互确认（自动化/无人值守用）")
    parser.add_argument("--only", action="append", default=[], help="只处理指定设备（IP 或名称，可重复）")
    parser.add_argument("--limit", type=int, help="只处理前 N 台（测试用）")
    parser.add_argument("--user", help="临时指定 SSH 用户名（覆盖清单里的账号）")
    parser.add_argument("--password", help="临时指定 SSH 密码（配合 --user 使用）")
    parser.add_argument("--secret", help="临时指定 super 密码（低权限账号提权用）")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    return parser


def build_credential_override(args) -> Credential | None:
    """把 --user/--password 组装成临时凭据；只给一半时报错，避免用错账号批量登录。"""
    if not args.user and not args.password:
        return None
    if not (args.user and args.password):
        raise SystemExit("--user 与 --password 必须同时提供（或都不提供，改用清单里的凭据）")
    return Credential(args.user, args.password, args.secret or "", "命令行")


def cmd_init(args) -> int:
    base = Path(args.config).parent if args.config != "config.json" else Path.cwd()
    config_path = Path(args.config)
    example = Path(__file__).resolve().parent.parent / "config.example.json"

    if config_path.exists():
        print(f"配置已存在，未覆盖: {config_path}")
    else:
        if not example.exists():
            print(f"未找到模板 {example}，请手工创建 config.json")
            return 2
        shutil.copyfile(example, config_path)
        print(f"已生成配置文件: {config_path}（请修改账号、团体名、Zabbix 地址后再执行）")

    inventory = base / "devices.xlsx"
    if inventory.exists():
        print(f"设备清单已存在，未覆盖: {inventory}")
    else:
        write_template(inventory)
        print(f"已生成设备清单模板: {inventory}")

    print("\n下一步:")
    print("  1. 编辑 devices.xlsx：IP、用户名、密码（密码列建议设为文本格式）")
    print("     账号密码只填在表里就够了，不必再写进 config.json")
    print("  2. 编辑 config.json 的 snmp 段：read_community / acl_number / acl_sources")
    print("  3. python run.py devices      确认清单与凭据解析正确")
    print("  4. python run.py snmp         预览要下发的命令（不碰设备）")
    print("  5. python run.py snmp --apply -y   批量登录并配置团体名")
    return 0


def cmd_devices(cfg, args) -> int:
    devices, rejected = load_inventory_from(cfg, args)
    print(f"\n清单解析结果：有效 {len(devices)} 台，被拒绝 {len(rejected)} 行\n")
    print(f"{'行':>3}  {'设备名':<18} {'管理IP':<16} {'端口':>5}  {'分组':<10} {'登录凭据':<34} {'密码':>4}")
    print("-" * 96)
    for device in devices:
        cred = f"{device.username}（{device.credential_source or '-'}）"
        print(f"{device.row:>3}  {device.label:<18} {device.ip:<16} {device.port:>5}  "
              f"{device.group or '-':<10} {cred:<34} {len(device.password):>3}位")
        if device.secret:
            print("      └ 已配 super 密码，登录后自动提权")
    if rejected:
        print("\n被拒绝的行：")
        for item in rejected:
            print(f"  第 {item.row} 行 ({item.ip}): {item.reason}")
    return 0


def load_inventory_from(cfg, args):
    inventory = Path(args.inventory) if args.inventory else cfg.resolve(str(cfg.get("inventory_file", "devices.xlsx")))
    credentials = cfg.section("credentials")
    devices, rejected = read_inventory(
        inventory,
        default_user=credentials.get("username", ""),
        default_password=credentials.get("password", ""),
        default_secret=credentials.get("secret", ""),
    )

    if args.only:
        keywords = [k.lower() for k in args.only]
        devices = [
            d for d in devices
            if any(k in d.ip.lower() or k in d.name.lower() for k in keywords)
        ]
        if not devices:
            raise SystemExit(f"--only {args.only} 没有匹配到任何设备")
    if args.limit:
        devices = devices[: args.limit]
    return devices, rejected


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("\n非交互环境执行写操作，请加 -y 确认。已中止。")
        return False
    answer = input(f"\n{prompt} [y/N]: ").strip().lower()
    return answer in ("y", "yes")


def print_snmp_plan(devices, snmp_cfg, credential, dry_run: bool) -> None:
    """执行前把「用哪个账号、配什么团体名、ACL 放行谁」打出来，避免盲跑。"""
    default_community = str(snmp_cfg.get("read_community") or "")
    acl_number = int(snmp_cfg.get("acl_number") or 0)
    sources = [s for s in (snmp_cfg.get("acl_sources") or []) if s]
    overrides = [d for d in devices if d.community and d.community != default_community]

    print("")
    print("=" * 78)
    print(f"团体名配置计划（{'预览，不下发' if dry_run else '实际下发'}）")
    print("=" * 78)
    print(f"  设备数量   : {len(devices)} 台")
    print(f"  团体名     : {default_community or '（清单逐台指定）'}")
    print(f"  ACL        : {acl_number or '不绑定'}"
          f"{'，放行 ' + '、'.join(sources) if sources else ''}")
    print(f"  写团体名   : {'配置' if snmp_cfg.get('write_community') else '不配置（推荐）'}")
    print(f"  trap 目标  : {snmp_cfg.get('trap_target') or '不配置'}")
    print(f"  登录账号   : {credential.username + '（命令行指定）' if credential else '按清单/配置逐台选择'}")
    if overrides:
        preview = "、".join(f"{d.label}={d.community}" for d in overrides[:5])
        more = f" 等 {len(overrides)} 台" if len(overrides) > 5 else ""
        print(f"  清单覆盖   : {preview}{more}")
    print("")


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "init":
        setup_logging(args.verbose)
        return cmd_init(args)

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"配置错误: {e}")
        return 2

    if args.workers:
        cfg.data["global"]["concurrency"] = max(1, min(args.workers, 50))

    if args.command == "devices":
        setup_logging(args.verbose)
        try:
            return cmd_devices(cfg, args)
        except (FileNotFoundError, ValueError) as e:
            print(f"清单读取失败: {e}")
            return 2

    stages = STAGE_CHOICES[args.command]
    dry_run = not args.apply

    try:
        credential = build_credential_override(args)
    except SystemExit as e:
        print(e)
        return 2

    if dry_run:
        # 预览模式不写设备：备份阶段也不做 save
        cfg.data.setdefault("backup", {})["save_before_backup"] = False

    missing = list()
    if "zabbix" in stages:
        if not cfg.get("zabbix.url"):
            missing.append("zabbix.url")
        if not cfg.get("zabbix.api_token") and not (
            cfg.get("zabbix.user") and cfg.get("zabbix.password")
        ):
            missing.append("zabbix.api_token 或 zabbix.user/password")
    if missing:
        print("配置缺少必填项: " + "、".join(missing))
        return 2

    try:
        devices, rejected = load_inventory_from(cfg, args)
    except (FileNotFoundError, ValueError) as e:
        print(f"清单读取失败: {e}")
        return 2

    if not devices:
        print("没有可处理的设备。")
        return 2

    snmp_cfg = cfg.section("snmp")
    if "snmp" in stages:
        default_community = str(snmp_cfg.get("read_community") or "")
        if not default_community and not any(d.community for d in devices):
            print("缺少团体名：请配置 snmp.read_community，或在设备清单「团体名」列逐台填写。")
            return 2
        print_snmp_plan(devices, snmp_cfg, credential, dry_run)

    run_dir = runner.prepare_run_dir(cfg)
    setup_logging(args.verbose, run_dir / "run.log")
    for item in rejected:
        log.warning("第 %d 行被跳过: %s", item.row, item.reason)

    if dry_run:
        log.info("预览模式：不会修改任何设备。加 --apply 才会真正下发配置 / 写入 Zabbix。")
    elif "snmp" in stages or "backup" in stages:
        actions = []
        if "snmp" in stages:
            actions.append("下发标准团体名")
        if "backup" in stages:
            actions.append("save 保存配置后备份")
        if not confirm(f"即将对 {len(devices)} 台设备执行写操作（{'、'.join(actions)}），确认继续？", args.yes):
            log.info("已取消。")
            return 2

    try:
        outcome = runner.execute(
            cfg, devices, stages, dry_run=dry_run, run_dir=run_dir, credential=credential
        )
    except KeyboardInterrupt:
        print("\n已中断。")
        return 130
    except runner.RunnerError as e:
        print(f"执行失败: {e}")
        return 2

    print(console_summary(outcome["results"], outcome["meta"]))
    print(f"报告: {outcome['files']['xlsx']}")
    print(f"摘要: {outcome['files']['markdown']}")
    print(f"日志: {run_dir / 'run.log'}")

    results = outcome["results"]
    failed = sum(
        1 for r in results
        if not r.reachable or (r.snmp and r.snmp.status == "失败") or (r.zabbix and r.zabbix.status in ("失败", "冲突"))
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
