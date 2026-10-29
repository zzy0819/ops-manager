#!/usr/bin/env python3
"""群晖 NAS 用户扫描 / 批量改密命令行工具。

示例：
    # 扫描用户
    python tools/nas_users_cli.py list --host 192.168.1.10 --account admin

    # 导出 CSV（不修改任何账号）
    python tools/nas_users_cli.py list --host 192.168.1.10 --account admin --csv users.csv

    # 批量重置密码（新密码从标准输入读取，避免进入 shell 历史；
    # DSM 管理员密码通过 SYNOLOGY_PASSWORD 环境变量或交互式输入提供）
    echo 'NewStr0ng!Pass' | python tools/nas_users_cli.py reset \
        --host 192.168.1.10 --account admin --users alice,bob --new-password-stdin

    # 先预演，不实际修改
    python tools/nas_users_cli.py reset --host 192.168.1.10 --account admin \
        --all --new-password-stdin --dry-run < new_password.txt

安全说明：
- 密码只从环境变量、交互式输入或标准输入读取，不作为命令行参数。
- 修改密码前会读取用户现有属性并原样回传，避免覆盖描述/邮箱/过期时间。
- 不记录密码；请自行确保终端和 shell 历史安全。
"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import sys

# 允许直接运行 tools/nas_users_cli.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.synology_service import (  # noqa: E402
    SynologyAuthError,
    SynologyClient,
    SynologyError,
    csv_safe,
    normalize_base_url,
    validate_password,
)


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--host', required=True, help='NAS 地址，如 192.168.1.10 或 https://nas:5001')
    parser.add_argument('--port', type=int, default=5001, help='DSM 端口，默认 5001')
    parser.add_argument('--http', action='store_true', help='使用 HTTP（默认 HTTPS）')
    parser.add_argument('--insecure', action='store_true', help='不校验 TLS 证书（自签名证书时使用）')
    parser.add_argument('--account', required=True, help='DSM 管理员账号（需属于 administrators 组）')
    parser.add_argument('--otp', default='', help='双重验证动态码（如启用）')
    parser.add_argument('--password-env', default='SYNOLOGY_PASSWORD', help='保存 DSM 管理员密码的环境变量名')
    parser.add_argument('--password-stdin', action='store_true', help='从标准输入读取 DSM 管理员密码')
    parser.add_argument('--timeout', type=float, default=20, help='HTTP 超时秒数，默认 20')


def read_admin_password(args) -> str:
    env_value = os.environ.get(args.password_env or '')
    if env_value:
        return env_value
    if args.password_stdin:
        line = sys.stdin.readline()
        if not line:
            raise SystemExit('标准输入中没有读取到 DSM 管理员密码')
        return line.rstrip('\r\n')
    return getpass.getpass('DSM 管理员密码: ')


def read_new_password(args) -> str:
    env_value = os.environ.get(args.new_password_env or '')
    if env_value:
        return env_value
    if args.new_password_stdin:
        line = sys.stdin.readline()
        if not line:
            raise SystemExit('标准输入中没有读取到新密码')
        return line.rstrip('\r\n')
    first = getpass.getpass('新密码: ')
    second = getpass.getpass('再次输入新密码: ')
    if first != second:
        raise SystemExit('两次输入的新密码不一致')
    return first


def login(args):
    try:
        base_url, hostname, _port = normalize_base_url(args.host, args.port, not args.http)
    except ValueError as exc:
        raise SystemExit(f'地址错误：{exc}')
    client = SynologyClient(base_url, verify_ssl=not args.insecure, timeout=args.timeout)
    password = read_admin_password(args)
    if not password:
        raise SystemExit('密码不能为空')
    try:
        client.login(args.account, password, args.otp or None)
    except SynologyAuthError as exc:
        suffix = '（请通过 --otp 提供动态验证码）' if exc.requires_otp else ''
        raise SystemExit(f'登录失败：{exc}{suffix}')
    except SynologyError as exc:
        raise SystemExit(f'连接失败：{exc}')
    return client, hostname


def print_users(users) -> None:
    print(f'共 {len(users)} 个本地用户')
    print('用户名\t管理员\t双重验证\t密码永不过期\t禁止改密\t上次改密\t用户组')
    for user in users:
        print(
            '\t'.join([
                user['name'],
                '是' if user['is_admin'] else '否',
                '已启用' if user['two_factor'] else ('未启用' if user['two_factor'] is False else '未知'),
                '是' if user['passwd_never_expire'] else '否',
                '是' if user['cannot_chg_passwd'] else '否',
                user['password_last_change'] or '未知',
                ', '.join(user['groups']) or '-',
            ])
        )


def write_csv(path: str, users) -> None:
    with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow([
            '用户名', '用户组', '管理员', '描述', '邮箱',
            '密码永不过期', '禁止用户改密', '上次改密', '双重验证',
        ])
        for user in users:
            writer.writerow([
                csv_safe(user['name']),
                csv_safe(', '.join(user['groups'])),
                '是' if user['is_admin'] else '否',
                csv_safe(user['description']),
                csv_safe(user['email']),
                '是' if user['passwd_never_expire'] else '否',
                '是' if user['cannot_chg_passwd'] else '否',
                csv_safe(user['password_last_change'] or ''),
                '已启用' if user['two_factor'] else ('未启用' if user['two_factor'] is False else '未知'),
            ])
    print(f'已导出 {len(users)} 个用户到 {path}')


def cmd_list(args) -> int:
    client, _host = login(args)
    try:
        users = client.list_users()
    except SynologyError as exc:
        raise SystemExit(f'扫描失败：{exc}')
    finally:
        client.logout()

    if args.csv:
        write_csv(args.csv, users)
    if args.json:
        print(json.dumps(users, ensure_ascii=False, indent=2))
    elif not args.csv:
        print_users(users)
    return 0


def cmd_reset(args) -> int:
    client, _host = login(args)
    try:
        users = client.list_users()
        policy = client.get_password_policy()
        password = read_new_password(args)
        if not password:
            raise SystemExit('新密码不能为空')

        by_name = {user['name']: user for user in users}
        if args.all:
            targets = [user for user in users if not user['is_guest'] and user['name'] != args.account]
        else:
            targets = []
            for name in (args.users or '').split(','):
                name = name.strip()
                if not name:
                    continue
                if name not in by_name:
                    raise SystemExit(f'用户不存在或不是本地用户：{name}')
                if name not in [user['name'] for user in targets]:
                    targets.append(by_name[name])

        if not targets:
            raise SystemExit('没有匹配的用户')

        blocked = [user['name'] for user in targets if user['is_admin'] and not args.allow_admin]
        if blocked:
            raise SystemExit(
                '以下管理员账号未授权重置：' + ', '.join(blocked)
                + '。如确需重置，请加 --allow-admin（高风险）。'
            )

        if not args.yes and not args.dry_run:
            print('即将重置以下用户的密码：' + ', '.join(user['name'] for user in targets))
            if input('输入 RESET 确认: ').strip() != 'RESET':
                raise SystemExit('已取消')

        results = []
        for user in targets:
            name = user['name']
            errors = validate_password(password, policy, username=name)
            if errors:
                results.append((name, 'failed', '；'.join(errors)))
                continue
            if args.dry_run:
                results.append((name, 'dry-run', '符合密码策略，未实际修改'))
                continue
            try:
                client.set_user_password(name, password)
                results.append((name, 'success', '密码已重置'))
            except SynologyError as exc:
                results.append((name, 'failed', str(exc)))

        print('\n处理结果：')
        for name, status, message in results:
            label = {'success': '成功', 'failed': '失败', 'dry-run': '预演'}[status]
            print(f'  [{label}] {name}: {message}')
        failed = sum(1 for _name, status, _msg in results if status == 'failed')
        return 1 if failed else 0
    finally:
        client.logout()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='扫描群晖 NAS 本地用户并批量修改密码（DSM Web API）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--version', action='version', version='nas_users_cli 1.0')
    sub = parser.add_subparsers(dest='command', required=True)

    list_parser = sub.add_parser('list', help='扫描用户')
    add_common_args(list_parser)
    list_parser.add_argument('--json', action='store_true', help='输出 JSON')
    list_parser.add_argument('--csv', default='', help='导出 CSV 文件路径')
    list_parser.set_defaults(func=cmd_list)

    reset_parser = sub.add_parser('reset', help='批量重置密码')
    add_common_args(reset_parser)
    group = reset_parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--users', help='逗号分隔的用户名，如 alice,bob')
    group.add_argument('--all', action='store_true', help='选择全部本地用户（排除 guest 和当前账号）')
    reset_parser.add_argument('--allow-admin', action='store_true', help='允许重置管理员账号（高风险）')
    reset_parser.add_argument('--new-password-env', default='SYNOLOGY_NEW_PASSWORD', help='保存新密码的环境变量名')
    reset_parser.add_argument('--new-password-stdin', action='store_true', help='从标准输入读取一行新密码')
    reset_parser.add_argument('--dry-run', action='store_true', help='只校验，不实际修改')
    reset_parser.add_argument('--yes', action='store_true', help='跳过交互式确认（自动化场景慎用）')
    reset_parser.set_defaults(func=cmd_reset)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
