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
from .config import ConfigError, load_config, require
from .inventory import read_inventory, write_template
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
  python run.py devices                                检查清单能否正确解析
  python run.py inspect                                批量巡检（只读）
  python run.py full --apply                           巡检 + 团体名 + Zabbix + 备份（实际执行）
  python run.py snmp --only 10.12.20.1 --apply         只给某台设备配团体名
  python run.py zabbix                                 预览 Zabbix 接入计划（不写入）
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
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    return parser


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
    print("  1. 编辑 devices.xlsx 填入真实设备（密码列建议设为文本格式）")
    print("  2. 编辑 config.json：credentials / snmp / zabbix")
    print("  3. python run.py devices      确认清单解析正确")
    print("  4. python run.py inspect      先跑只读巡检")
    return 0


def cmd_devices(cfg, args) -> int:
    devices, rejected = load_inventory_from(cfg, args)
    print(f"\n清单解析结果：有效 {len(devices)} 台，被拒绝 {len(rejected)} 行\n")
    print(f"{'行':>3}  {'设备名':<18} {'管理IP':<16} {'端口':>5}  {'分组':<10} {'凭据'}")
    print("-" * 78)
    for device in devices:
        print(f"{device.row:>3}  {device.label:<18} {device.ip:<16} {device.port:>5}  "
              f"{device.group or '-':<10} {device.username}")
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

    if dry_run:
        # 预览模式不写设备：备份阶段也不做 save
        cfg.data.setdefault("backup", {})["save_before_backup"] = False

    missing = []
    if "snmp" in stages:
        missing += require(cfg, "snmp.read_community")
    if "zabbix" in stages:
        missing += require(cfg, "zabbix.url")
        if not cfg.get("zabbix.api_token") and not (cfg.get("zabbix.user") and cfg.get("zabbix.password")):
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
        outcome = runner.execute(cfg, devices, stages, dry_run=dry_run, run_dir=run_dir)
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
