#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""群晖 NAS 用户扫描与批量改密脚本（单文件，仅使用 Python 标准库）。

功能：
- 通过 DSM Web API 登录（支持 HTTPS、自签名证书、双重验证）
- 扫描全部本地用户，显示用户组、管理员、密码策略、上次改密、2FA
- 按用户名列表或全部用户批量重置密码
- 改密前读取用户当前属性并原样回传，避免覆盖描述、邮箱、过期时间等
- 支持预演（--dry-run）、CSV 导出、可选审计日志

快速开始：
    # 交互模式：直接运行，按提示输入
    python synology_user_manager.py

    # 只扫描用户
    python synology_user_manager.py list --host 192.168.1.10 --account admin

    # 导出 CSV
    python synology_user_manager.py list --host 192.168.1.10 --account admin --csv users.csv

    # 批量改密（新密码从标准输入读取，避免进入 shell 历史）
    python synology_user_manager.py reset --host 192.168.1.10 --account admin \
        --users alice,bob --new-password-stdin < new_password.txt

    # 预演：只校验密码策略，不实际修改
    python synology_user_manager.py reset --host 192.168.1.10 --account admin \
        --all --new-password-stdin --dry-run < new_password.txt

安全说明：
- 建议使用仅属于 administrators 组的专用管理员账号。
- 密码只从环境变量、交互式输入或标准输入读取，不放在命令行参数中。
- 脚本不会把密码写入日志或审计文件。
- 仅支持 DSM 本地用户（type=local），不管理 LDAP / 域用户。
"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any

DEFAULT_TIMEOUT = 20
DEFAULT_PORT_HTTPS = 5001
DEFAULT_PORT_HTTP = 5000

API_ERRORS = {
    100: '群晖返回未知错误',
    101: '请求参数无效（可能是 DSM 版本不支持该字段）',
    102: '群晖上不存在该 API',
    103: '群晖上不存在该 API 方法',
    104: '当前 DSM 版本不支持该 API 版本',
    105: '当前账号没有执行该操作的权限',
    106: 'DSM 会话已超时，请重新登录',
    107: 'DSM 会话被其他登录中断，请重新登录',
    109: '网络连接不稳定或系统繁忙，请稍后重试',
    110: '网络连接不稳定或系统繁忙，请稍后重试',
    111: '网络连接不稳定或系统繁忙，请稍后重试',
    114: '请求缺少必要参数',
    119: 'DSM 会话无效，请重新登录',
    150: '请求来源 IP 与登录 IP 不一致',
}

AUTH_ERRORS = {
    400: '账号或密码错误',
    401: '该账号已被停用',
    402: '该账号没有登录权限',
    403: '该账号已启用双重验证，请输入动态验证码',
    404: '动态验证码错误',
    405: '该账号没有登录权限',
    406: '该账号强制要求双重验证，请输入动态验证码',
    407: '来源 IP 已被禁止登录',
    408: '密码已过期，且不允许修改',
    409: '密码已过期',
    410: '必须先修改密码才能登录',
    411: '登录权限不足',
    412: '该账号已被锁定',
}

USER_LIST_FIELDS = [
    'description',
    'email',
    'expired',
    'cannot_chg_passwd',
    'passwd_never_expire',
    'password_last_change',
    'groups',
    '2fa_status',
]
USER_LIST_FIELDS_BASIC = [
    'description',
    'email',
    'expired',
    'cannot_chg_passwd',
    'passwd_never_expire',
    'password_last_change',
]
USER_GET_FIELDS = [
    'description',
    'email',
    'expired',
    'cannot_chg_passwd',
    'passwd_never_expire',
    'password_last_change',
]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class DsmError(Exception):
    """群晖操作异常基类。"""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class DsmAuthError(DsmError):
    """登录失败。requires_otp=True 表示需要双重验证码。"""

    def __init__(self, message: str, code: int | None = None, requires_otp: bool = False):
        super().__init__(message, code)
        self.requires_otp = requires_otp


class DsmAPIError(DsmError):
    """DSM API 返回 success=false。"""


class DsmSessionExpired(DsmAPIError):
    """DSM 会话失效。"""


# ---------------------------------------------------------------------------
# 输入与数据规范化
# ---------------------------------------------------------------------------


def _clean_host(value: str) -> str:
    return re.sub(r'[\r\n\x00]', '', str(value or '')).strip()


def normalize_base_url(host: str, port: int = DEFAULT_PORT_HTTPS, use_https: bool = True) -> str:
    """把用户输入规范化为 scheme://host:port，拒绝路径、账号等。"""
    raw = _clean_host(host)
    if not raw:
        raise ValueError('NAS 地址不能为空')
    if '://' not in raw:
        raw = f"{'https' if use_https else 'http'}://{raw}"

    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError('仅支持 http 或 https 协议')
    if parsed.username or parsed.password:
        raise ValueError('NAS 地址中不能包含用户名或密码')
    if parsed.path not in ('', '/'):
        raise ValueError('NAS 地址不能包含路径，请只填写主机名或 IP')
    if parsed.query or parsed.fragment:
        raise ValueError('NAS 地址不能包含查询参数')
    if not parsed.hostname:
        raise ValueError('NAS 地址格式不正确')
    if re.search(r'\s', parsed.hostname):
        raise ValueError('NAS 地址不能包含空格')

    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise ValueError('NAS 端口格式不正确') from exc
    final_port = explicit_port if explicit_port is not None else int(port)
    if not 1 <= final_port <= 65535:
        raise ValueError('NAS 端口必须在 1-65535 之间')

    netloc_host = f'[{parsed.hostname}]' if ':' in parsed.hostname else parsed.hostname
    return f'{parsed.scheme}://{netloc_host}:{final_port}'


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on', 'enabled'}
    return False


def bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {'1', 'true', 'yes', 'on', 'enabled'}:
            return True
        if text in {'0', 'false', 'no', 'off', 'disabled'}:
            return False
    return None


def parse_groups(value: Any) -> list[str]:
    """兼容 DSM 不同版本的 groups 返回格式。"""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith('['):
            try:
                return parse_groups(json.loads(text))
            except (ValueError, TypeError):
                pass
        return [item.strip() for item in text.split(',') if item.strip()]
    if isinstance(value, dict):
        value = [value]
    if isinstance(value, (list, tuple, set)):
        groups: list[str] = []
        for item in value:
            if isinstance(item, dict):
                name = item.get('name') or item.get('group_name') or item.get('group')
                if name:
                    groups.append(str(name))
            elif item is not None:
                text = str(item).strip()
                if text:
                    groups.append(text)
        return list(dict.fromkeys(groups))
    return []


def format_last_change(value: Any) -> str | None:
    """DSM 的 password_last_change 通常是自 1970-01-01 起的天数。"""
    if value in (None, '', 0, '0'):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    if number <= 0:
        return None
    try:
        if number < 100000:
            return (date(1970, 1, 1) + timedelta(days=number)).isoformat()
        return datetime.fromtimestamp(number).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return str(value)


def normalize_user(raw: dict[str, Any]) -> dict[str, Any]:
    name = str(raw.get('name') or '').strip()
    if not name:
        raise ValueError('用户数据缺少 name 字段')

    groups = parse_groups(raw.get('groups'))
    is_admin = bool({item.lower() for item in groups} & {'administrators', 'admin'})

    raw_fields = {}
    for key in ('expired', 'description', 'email', 'cannot_chg_passwd', 'passwd_never_expire'):
        if key in raw:
            raw_fields[key] = raw[key]

    return {
        'name': name,
        'uid': raw.get('uid'),
        'description': str(raw.get('description') or ''),
        'email': str(raw.get('email') or ''),
        'groups': groups,
        'groups_known': 'groups' in raw,
        'is_admin': is_admin,
        'is_guest': name.lower() == 'guest',
        'is_builtin': name.lower() in {'admin', 'guest'},
        'expired': raw.get('expired'),
        'cannot_chg_passwd': parse_bool(raw.get('cannot_chg_passwd')),
        'passwd_never_expire': parse_bool(raw.get('passwd_never_expire')),
        'password_last_change': format_last_change(raw.get('password_last_change')),
        'two_factor': bool_or_none(raw.get('2fa_status', raw.get('two_factor_auth'))),
        'raw': raw_fields,
    }


def default_password_policy() -> dict[str, Any]:
    return {
        'available': False,
        'min_length': 8,
        'min_length_enable': True,
        'mixed_case': True,
        'included_numeric_char': True,
        'included_special_char': False,
        'exclude_username': True,
        'history_num': 0,
        'password_must_change': False,
    }


def normalize_password_policy(data: dict[str, Any]) -> dict[str, Any]:
    strong = data.get('strong_password') if isinstance(data, dict) else None
    strong = strong if isinstance(strong, dict) else {}
    policy = default_password_policy()
    policy['available'] = True
    try:
        policy['min_length'] = max(1, int(strong.get('min_length', 8)))
    except (TypeError, ValueError):
        policy['min_length'] = 8
    policy['min_length_enable'] = parse_bool(strong.get('min_length_enable', True))
    policy['mixed_case'] = parse_bool(strong.get('mixed_case', True))
    policy['included_numeric_char'] = parse_bool(strong.get('included_numeric_char', True))
    policy['included_special_char'] = parse_bool(strong.get('included_special_char', False))
    policy['exclude_username'] = parse_bool(strong.get('exclude_username', True))
    try:
        policy['history_num'] = max(0, int(strong.get('history_num', 0) or 0))
    except (TypeError, ValueError):
        policy['history_num'] = 0
    policy['password_must_change'] = parse_bool(data.get('password_must_change', False))
    return policy


def validate_password(password: str, policy: dict[str, Any], username: str | None = None) -> list[str]:
    """按群晖密码策略校验，返回中文错误列表。"""
    errors: list[str] = []
    if not password:
        return ['新密码不能为空']
    if len(password) > 256:
        errors.append('新密码不能超过 256 个字符')
    min_length = int(policy.get('min_length') or 8)
    if policy.get('min_length_enable', True) and len(password) < min_length:
        errors.append(f'新密码至少需要 {min_length} 个字符')
    if policy.get('mixed_case') and not (
        any(ch.islower() for ch in password) and any(ch.isupper() for ch in password)
    ):
        errors.append('新密码必须同时包含大写和小写字母')
    if policy.get('included_numeric_char') and not any(ch.isdigit() for ch in password):
        errors.append('新密码必须包含数字')
    if policy.get('included_special_char') and not any(not ch.isalnum() for ch in password):
        errors.append('新密码必须包含特殊字符')
    if policy.get('exclude_username') and username and username.lower() in password.lower():
        errors.append('新密码不能包含用户名')
    return errors


def policy_text(policy: dict[str, Any]) -> str:
    parts = []
    if policy.get('min_length_enable'):
        parts.append(f"至少 {policy.get('min_length', 8)} 位")
    if policy.get('mixed_case'):
        parts.append('大小写字母')
    if policy.get('included_numeric_char'):
        parts.append('数字')
    if policy.get('included_special_char'):
        parts.append('特殊字符')
    if policy.get('exclude_username'):
        parts.append('不含用户名')
    return '、'.join(parts) or '无强密码要求'


# ---------------------------------------------------------------------------
# DSM 客户端（标准库实现）
# ---------------------------------------------------------------------------


class DsmClient:
    """最小的 DSM Web API 客户端。"""

    def __init__(self, base_url: str, verify_ssl: bool = True, timeout: float = DEFAULT_TIMEOUT):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError('NAS 地址格式不正确')
        self.base_url = base_url.rstrip('/')
        self.timeout = float(timeout)
        self.sid: str | None = None
        self.account: str | None = None
        self.context = None
        if parsed.scheme == 'https':
            self.context = ssl.create_default_context()
            if not verify_ssl:
                self.context.check_hostname = False
                self.context.verify_mode = ssl.CERT_NONE

    # -- HTTP -------------------------------------------------------------

    @staticmethod
    def _encode_params(params: dict[str, Any]) -> dict[str, str]:
        encoded: dict[str, str] = {}
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, bool):
                encoded[key] = 'true' if value else 'false'
            elif isinstance(value, (list, tuple, dict)):
                encoded[key] = json.dumps(value, ensure_ascii=False)
            else:
                encoded[key] = str(value)
        return encoded

    def _request(self, path: str, params: dict[str, Any], *, get: bool = False) -> dict[str, Any]:
        data = urllib.parse.urlencode(self._encode_params(params)).encode('utf-8')
        url = self.base_url + path
        if get:
            url += '?' + data.decode('utf-8')
            body = None
        else:
            body = data
        request = urllib.request.Request(
            url,
            data=body,
            method='GET' if get else 'POST',
            headers={
                'User-Agent': 'SynologyUserManager/1.0',
                'Accept': 'application/json',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=self.context
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise DsmError(f'群晖返回 HTTP {exc.code}，请检查 DSM 地址和端口。') from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, ssl.SSLError):
                raise DsmError(
                    'TLS 证书校验失败。若 NAS 使用自签名证书，请加 --insecure 后重试。'
                ) from exc
            raise DsmError(f'无法连接群晖：{reason}') from exc
        except (TimeoutError, OSError) as exc:
            raise DsmError(f'连接群晖失败：{exc}') from exc

        try:
            text = raw.decode('utf-8')
            body_json = json.loads(text)
        except (UnicodeDecodeError, ValueError) as exc:
            raise DsmError(
                '群晖返回的不是 JSON 数据，可能端口错误，或被反向代理拦截。'
            ) from exc
        if not isinstance(body_json, dict):
            raise DsmError('群晖返回的数据格式不正确。')
        return body_json

    def _raise_api_error(self, body: dict[str, Any], *, auth: bool = False) -> None:
        error = body.get('error') or {}
        try:
            code = int(error.get('code')) if isinstance(error, dict) else int(error)
        except (TypeError, ValueError):
            code = None
        message = (AUTH_ERRORS if auth else API_ERRORS).get(
            code or -1, f'群晖返回错误（错误码 {code}）'
        )
        if auth:
            raise DsmAuthError(message, code=code, requires_otp=code in (403, 406))
        if code in {105, 106, 107, 119}:
            raise DsmSessionExpired(message, code=code)
        raise DsmAPIError(message, code=code)

    def _api(
        self,
        api: str,
        params: dict[str, Any],
        *,
        get: bool = False,
        auth: bool = False,
        path: str = '/webapi/entry.cgi',
    ) -> dict[str, Any]:
        payload = {'api': api, **params}
        if self.sid and not auth:
            payload['_sid'] = self.sid
        body = self._request(path, payload, get=get)
        if not body.get('success'):
            self._raise_api_error(body, auth=auth)
        data = body.get('data')
        return data if isinstance(data, dict) else {'data': data}

    # -- 登录/注销 --------------------------------------------------------

    def login(self, account: str, password: str, otp_code: str | None = None) -> str:
        account = _clean_host(account)
        if not account or not password:
            raise DsmAuthError('登录账号和密码不能为空')

        otp_code = _clean_host(otp_code) or None
        last_error: DsmAuthError | None = None
        for version in (6, 5, 3, 1):
            params = {
                'api': 'SYNO.API.Auth',
                'version': version,
                'method': 'login',
                'account': account,
                'passwd': password,
                'session': 'OpsManagerScript',
                'format': 'sid',
            }
            if otp_code:
                params['otp_code'] = otp_code
            try:
                data = self._api(
                    'SYNO.API.Auth', params, auth=True, path='/webapi/auth.cgi'
                )
            except DsmAuthError as exc:
                if exc.code in (101, 104):
                    last_error = exc
                    continue
                raise
            sid = data.get('sid')
            if not sid:
                raise DsmAuthError('登录响应中没有会话 ID，请确认 DSM 版本和账号权限。')
            self.sid = str(sid)
            self.account = account
            return self.sid
        raise last_error or DsmAuthError('无法与当前 DSM 版本建立登录会话')

    def logout(self) -> None:
        if not self.sid:
            return
        try:
            self._api(
                'SYNO.API.Auth',
                {
                    'api': 'SYNO.API.Auth',
                    'version': 1,
                    'method': 'logout',
                    'session': 'OpsManagerScript',
                    '_sid': self.sid,
                },
                auth=True,
                path='/webapi/auth.cgi',
            )
        except DsmError:
            pass
        finally:
            self.sid = None

    # -- 用户 -------------------------------------------------------------

    def _list_users_with_fields(self, fields: list[str]) -> list[dict[str, Any]]:
        data = self._api(
            'SYNO.Core.User',
            {
                'version': 1,
                'method': 'list',
                'type': 'local',
                'offset': 0,
                'limit': -1,
                'sort_by': 'name',
                'sort_direction': 'ASC',
                'additional': fields,
            },
            get=True,
        )
        users = data.get('users') if isinstance(data, dict) else None
        if not isinstance(users, list):
            raise DsmAPIError('群晖返回的用户列表格式不正确')
        return [normalize_user(item) for item in users if isinstance(item, dict)]

    def list_users(self) -> list[dict[str, Any]]:
        """扫描全部本地用户；旧版 DSM 不支持附加字段时自动降级。"""
        field_sets = (
            USER_LIST_FIELDS,
            [field for field in USER_LIST_FIELDS if field != '2fa_status'],
            USER_LIST_FIELDS_BASIC,
            [],
        )
        last_error: DsmAPIError | None = None
        for fields in field_sets:
            try:
                return self._list_users_with_fields(fields)
            except DsmAPIError as exc:
                if exc.code not in {101, 103, 104, 114}:
                    raise
                last_error = exc
        raise last_error or DsmAPIError('群晖用户列表接口不可用')

    def get_user(self, name: str) -> dict[str, Any]:
        """读取单个用户，优先带附加字段；失败时降级。"""
        data: dict[str, Any] = {}
        for fields in (USER_GET_FIELDS, []):
            try:
                data = self._api(
                    'SYNO.Core.User',
                    {
                        'version': 1,
                        'method': 'get',
                        'type': 'local',
                        'name': name,
                        'additional': fields,
                    },
                    get=True,
                )
                break
            except DsmAPIError as exc:
                if fields and exc.code in {101, 103, 104, 114}:
                    continue
                raise
        users = data.get('users') if isinstance(data, dict) else None
        if not users or not isinstance(users, list) or not isinstance(users[0], dict):
            raise DsmAPIError(f'未找到用户 {name}')
        return normalize_user(users[0])

    def get_password_policy(self) -> dict[str, Any]:
        try:
            data = self._api(
                'SYNO.Core.User.PasswordPolicy',
                {'version': 1, 'method': 'get'},
                get=True,
            )
            return normalize_password_policy(data)
        except DsmSessionExpired:
            raise
        except DsmAPIError as exc:
            if exc.code in {102, 103, 104, 105}:
                return default_password_policy()
            raise
        except DsmError:
            return default_password_policy()

    def set_user_password(
        self,
        name: str,
        password: str,
        current: dict[str, Any] | None = None,
    ) -> None:
        """重置密码并保留原有账号属性。

        DSM 的 set 是整体更新接口：只传 name/password 可能把 description、
        email、expired、cannot_chg_passwd、passwd_never_expire 重置。
        因此先 get 当前值，再原样回传。
        """
        current = current or self.get_user(name)
        if current['name'] != name:
            raise DsmAPIError('群晖返回的用户名与请求不一致，已中止改密')

        raw = current['raw']
        required = ('expired', 'cannot_chg_passwd', 'passwd_never_expire')
        missing = [key for key in required if key not in raw]
        if missing:
            raise DsmAPIError(
                '无法读取该用户的完整属性（' + ', '.join(missing)
                + '），为避免覆盖账号设置已中止改密'
            )

        self._api(
            'SYNO.Core.User',
            {
                'version': 1,
                'method': 'set',
                'name': current['name'],
                'new_name': current['name'],
                'password': password,
                'description': raw.get('description') or '',
                'email': raw.get('email') or '',
                'expired': raw.get('expired') or 'never',
                'cannot_chg_passwd': parse_bool(raw.get('cannot_chg_passwd')),
                'passwd_never_expire': parse_bool(raw.get('passwd_never_expire')),
                'notify_by_email': False,
                'send_password': False,
            },
            get=False,
        )


# ---------------------------------------------------------------------------
# 输出与文件
# ---------------------------------------------------------------------------


def csv_safe(value: Any) -> str:
    text = '' if value is None else str(value)
    if text.startswith(('=', '+', '-', '@', '\t', '\r')):
        return "'" + text
    return text


def print_users(users: list[dict[str, Any]]) -> None:
    print(f'\n共扫描到 {len(users)} 个本地用户：')
    print('-' * 100)
    print(f"{'用户名':<18}{'管理员':<8}{'2FA':<10}{'密码策略':<22}{'上次改密':<13}用户组")
    print('-' * 100)
    for user in users:
        policy = []
        if user['passwd_never_expire']:
            policy.append('永不过期')
        if user['cannot_chg_passwd']:
            policy.append('禁止自改')
        twofa = '已启用' if user['two_factor'] else ('未启用' if user['two_factor'] is False else '未知')
        print(
            f"{user['name']:<18}"
            f"{'是' if user['is_admin'] else '否':<8}"
            f"{twofa:<10}"
            f"{('/'.join(policy) or '默认'):<22}"
            f"{(user['password_last_change'] or '未知'):<13}"
            f"{', '.join(user['groups']) or ('未知' if not user['groups_known'] else '-')}"
        )
    print('-' * 100)


def write_csv(path: str, users: list[dict[str, Any]]) -> None:
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


def append_audit(path: str | None, host: str, account: str, target: str,
                 status: str, message: str) -> None:
    if not path:
        return
    new_file = not os.path.exists(path)
    encoding = 'utf-8-sig' if new_file else 'utf-8'
    with open(path, 'a', encoding=encoding, newline='') as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(['时间', 'NAS', '登录账号', '目标用户', '结果', '说明'])
        writer.writerow([
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            csv_safe(host),
            csv_safe(account),
            csv_safe(target),
            status,
            csv_safe(message),
        ])


# ---------------------------------------------------------------------------
# 交互输入
# ---------------------------------------------------------------------------


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


def connect(args) -> tuple[DsmClient, str]:
    try:
        base_url = normalize_base_url(args.host, args.port, not args.http)
    except ValueError as exc:
        raise SystemExit(f'地址错误：{exc}')
    client = DsmClient(base_url, verify_ssl=not args.insecure, timeout=args.timeout)
    password = read_admin_password(args)
    if not password:
        raise SystemExit('密码不能为空')
    try:
        client.login(args.account, password, args.otp or None)
    except DsmAuthError as exc:
        suffix = '（请通过 --otp 提供动态验证码）' if exc.requires_otp else ''
        raise SystemExit(f'登录失败：{exc}{suffix}')
    except DsmError as exc:
        raise SystemExit(f'连接失败：{exc}')
    return client, base_url


# ---------------------------------------------------------------------------
# 改密流程
# ---------------------------------------------------------------------------


def resolve_targets(users: list[dict[str, Any]], account: str,
                    users_arg: str | None, all_flag: bool) -> list[dict[str, Any]]:
    by_name = {user['name']: user for user in users}
    if all_flag:
        return [
            user for user in users
            if not user['is_guest'] and user['name'] != account
        ]

    targets: list[dict[str, Any]] = []
    seen = set()
    for name in (users_arg or '').split(','):
        name = name.strip()
        if not name or name in seen:
            continue
        if name not in by_name:
            raise SystemExit(f'用户不存在或不是本地用户：{name}')
        seen.add(name)
        targets.append(by_name[name])
    return targets


def check_admin_permissions(targets: list[dict[str, Any]], allow_admin: bool) -> None:
    admins = [user['name'] for user in targets if user['is_admin']]
    unknown = [user['name'] for user in targets if not user['groups_known']]
    if admins and not allow_admin:
        raise SystemExit(
            '以下管理员账号未授权重置：' + ', '.join(admins)
            + '。如确需重置，请加 --allow-admin（高风险）。'
        )
    if unknown and not allow_admin:
        raise SystemExit(
            '当前 DSM 未返回用户组信息，无法识别管理员：' + ', '.join(unknown)
            + '。如继续，请加 --allow-admin（高风险）。'
        )


def confirm_targets(targets: list[dict[str, Any]], allow_admin: bool,
                    assume_yes: bool, dry_run: bool) -> None:
    check_admin_permissions(targets, allow_admin)
    print(f'\n将要处理 {len(targets)} 个用户：')
    for user in targets:
        tag = ' [管理员]' if user['is_admin'] else ''
        print(f"  - {user['name']}{tag}")
    if dry_run:
        print('\n*** 预演模式：只校验密码策略，不会修改任何账号 ***')
        return
    if assume_yes:
        return
    print('\n此操作会立即修改上述用户的密码。')
    answer = input('输入 RESET 确认执行（其他任何输入取消）: ').strip()
    if answer != 'RESET':
        raise SystemExit('已取消')


def execute_reset(
    client: DsmClient,
    policy: dict[str, Any],
    targets: list[dict[str, Any]],
    new_password: str,
    allow_admin: bool,
    dry_run: bool,
    host: str,
    account: str,
    audit_log: str | None,
) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    session_expired = False

    for user in targets:
        name = user['name']
        if name == account:
            message = '不能通过当前登录会话重置自身密码'
            results.append((name, 'skipped', message))
            append_audit(audit_log, host, account, name, 'skipped', message)
            continue

        errors = validate_password(new_password, policy, username=name)
        if errors:
            message = '；'.join(errors)
            results.append((name, 'failed', message))
            append_audit(audit_log, host, account, name, 'failed', message)
            continue

        if session_expired:
            message = 'DSM 会话已失效，未执行'
            results.append((name, 'skipped', message))
            append_audit(audit_log, host, account, name, 'skipped', message)
            continue

        if dry_run:
            message = f'符合密码策略（{policy_text(policy)}），未实际修改'
            results.append((name, 'dry-run', message))
            continue

        try:
            current = client.get_user(name)
            if current['is_admin'] and not allow_admin:
                message = '该账号当前是管理员，未授权重置'
                results.append((name, 'skipped', message))
                append_audit(audit_log, host, account, name, 'skipped', message)
                continue
            client.set_user_password(name, new_password, current=current)
            message = '密码已重置'
            results.append((name, 'success', message))
            append_audit(audit_log, host, account, name, 'success', message)
        except DsmSessionExpired as exc:
            session_expired = True
            message = str(exc)
            results.append((name, 'failed', message))
            append_audit(audit_log, host, account, name, 'failed', message)
        except DsmError as exc:
            message = str(exc)
            results.append((name, 'failed', message))
            append_audit(audit_log, host, account, name, 'failed', message)
        except Exception as exc:  # 防御性兜底
            message = f'未预期错误：{exc}'
            results.append((name, 'failed', message))
            append_audit(audit_log, host, account, name, 'failed', message)

    return results


def print_results(results: list[tuple[str, str, str]]) -> None:
    labels = {'success': '成功', 'failed': '失败', 'skipped': '跳过', 'dry-run': '预演'}
    print('\n处理结果：')
    for name, status, message in results:
        print(f"  [{labels.get(status, status)}] {name}: {message}")
    counts = {
        'success': sum(1 for _n, status, _m in results if status == 'success'),
        'failed': sum(1 for _n, status, _m in results if status == 'failed'),
        'skipped': sum(1 for _n, status, _m in results if status == 'skipped'),
        'dry-run': sum(1 for _n, status, _m in results if status == 'dry-run'),
    }
    print(
        f"\n汇总：成功 {counts['success']}，失败 {counts['failed']}，"
        f"跳过 {counts['skipped']}，预演 {counts['dry-run']}"
    )


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------


def cmd_list(args) -> int:
    client, _base_url = connect(args)
    try:
        users = client.list_users()
    except DsmSessionExpired as exc:
        raise SystemExit(f'扫描失败：{exc}')
    except DsmError as exc:
        raise SystemExit(f'扫描失败：{exc}')
    finally:
        client.logout()

    if args.csv:
        write_csv(args.csv, users)
    if args.json:
        print(json.dumps(users, ensure_ascii=False, indent=2))
    elif not args.csv:
        print_users(users)
    return EXIT_OK


def cmd_reset(args) -> int:
    client, base_url = connect(args)
    try:
        try:
            users = client.list_users()
            policy = client.get_password_policy()
        except DsmSessionExpired as exc:
            raise SystemExit(f'扫描失败：{exc}')
        except DsmError as exc:
            raise SystemExit(f'扫描失败：{exc}')

        targets = resolve_targets(users, args.account, args.users, args.all)
        if not targets:
            raise SystemExit('没有匹配的用户')
        check_admin_permissions(targets, args.allow_admin)

        new_password = read_new_password(args)
        if not new_password:
            raise SystemExit('新密码不能为空')
        errors = validate_password(new_password, policy)
        if errors:
            raise SystemExit('新密码不符合群晖密码策略：' + '；'.join(errors))
        print(f'群晖密码策略：{policy_text(policy)}')

        confirm_targets(targets, args.allow_admin, args.yes, args.dry_run)
        results = execute_reset(
            client, policy, targets, new_password, args.allow_admin,
            args.dry_run, base_url, args.account, args.audit_log,
        )
        print_results(results)
        return EXIT_FAILED if any(status == 'failed' for _n, status, _m in results) else EXIT_OK
    finally:
        client.logout()


def cmd_interactive() -> int:
    print('=' * 62)
    print(' 群晖 NAS 用户扫描 / 批量改密（单文件脚本）')
    print('=' * 62)
    host = input('NAS 地址（如 192.168.1.10）: ').strip()
    port_text = input('端口 [5001]: ').strip() or '5001'
    try:
        port = int(port_text)
    except ValueError:
        print('端口必须是数字')
        return EXIT_USAGE
    https_text = input('使用 HTTPS? [Y/n]: ').strip().lower()
    use_https = https_text not in ('n', 'no', '0', 'false')
    account = input('管理员账号: ').strip()
    if not host or not account:
        print('地址和账号不能为空')
        return EXIT_USAGE
    password = getpass.getpass('DSM 管理员密码: ')
    otp = input('双重验证码（没有直接回车）: ').strip()

    try:
        base_url = normalize_base_url(host, port, use_https)
    except ValueError as exc:
        print(f'地址错误：{exc}')
        return EXIT_USAGE
    verify_text = input('校验 TLS 证书? [Y/n，自签名证书选 n]: ').strip().lower()
    verify_ssl = verify_text not in ('n', 'no', '0', 'false')
    client = DsmClient(base_url, verify_ssl=verify_ssl)
    try:
        client.login(account, password, otp or None)
    except DsmAuthError as exc:
        suffix = '（请重新运行并填写动态验证码）' if exc.requires_otp else ''
        print(f'登录失败：{exc}{suffix}')
        return EXIT_FAILED
    except DsmError as exc:
        print(f'连接失败：{exc}')
        return EXIT_FAILED

    try:
        users = client.list_users()
        policy = client.get_password_policy()
        print_users(users)
        print(f'密码策略：{policy_text(policy)}')
        selection = input('\n要重置的用户名（逗号分隔，all=全部，直接回车退出）: ').strip()
        if not selection:
            print('已退出，未修改任何账号。')
            return EXIT_OK
        try:
            targets = resolve_targets(users, account, selection, selection.lower() == 'all')
        except SystemExit as exc:
            print(exc)
            return EXIT_USAGE
        if not targets:
            print('没有匹配的用户。')
            return EXIT_USAGE

        allow_text = input('允许重置管理员/未识别账号? [y/N]: ').strip().lower()
        allow_admin = allow_text in ('y', 'yes', '1', 'true')
        check_admin_permissions(targets, allow_admin)

        first = getpass.getpass('新密码: ')
        second = getpass.getpass('再次输入新密码: ')
        if first != second:
            print('两次输入的新密码不一致。')
            return EXIT_USAGE
        errors = validate_password(first, policy)
        if errors:
            print('新密码不符合策略：' + '；'.join(errors))
            return EXIT_USAGE

        confirm_targets(targets, allow_admin, False, False)
        results = execute_reset(
            client, policy, targets, first, allow_admin, False,
            base_url, account, 'synology_password_reset_audit.csv',
        )
        print_results(results)
        return EXIT_FAILED if any(status == 'failed' for _n, status, _m in results) else EXIT_OK
    except DsmError as exc:
        print(f'操作失败：{exc}')
        return EXIT_FAILED
    finally:
        client.logout()


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--host', required=True, help='NAS 地址，如 192.168.1.10 或 https://nas:5001')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT_HTTPS, help='DSM 端口（默认 5001）')
    parser.add_argument('--http', action='store_true', help='使用 HTTP（默认 HTTPS）')
    parser.add_argument('--insecure', action='store_true', help='不校验 TLS 证书（自签名证书时使用）')
    parser.add_argument('--account', required=True, help='DSM 管理员账号（需属于 administrators 组）')
    parser.add_argument('--otp', default='', help='双重验证动态码')
    parser.add_argument('--password-env', default='SYNOLOGY_PASSWORD', help='管理员密码所在环境变量')
    parser.add_argument('--password-stdin', action='store_true', help='从标准输入读取管理员密码')
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT, help='HTTP 超时秒数')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='扫描群晖 NAS 本地用户并批量修改密码（DSM Web API，单文件标准库实现）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--version', action='version', version='synology_user_manager 1.0')
    sub = parser.add_subparsers(dest='command')

    list_parser = sub.add_parser('list', help='扫描用户')
    add_connection_args(list_parser)
    list_parser.add_argument('--json', action='store_true', help='输出 JSON')
    list_parser.add_argument('--csv', default='', help='导出 CSV 文件')
    list_parser.set_defaults(func=cmd_list)

    reset_parser = sub.add_parser('reset', help='批量重置密码')
    add_connection_args(reset_parser)
    group = reset_parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--users', help='逗号分隔的用户名，如 alice,bob')
    group.add_argument('--all', action='store_true', help='全部本地用户（排除 guest 和当前账号）')
    reset_parser.add_argument('--allow-admin', action='store_true', help='允许重置管理员账号（高风险）')
    reset_parser.add_argument('--new-password-env', default='SYNOLOGY_NEW_PASSWORD', help='新密码所在环境变量')
    reset_parser.add_argument('--new-password-stdin', action='store_true', help='从标准输入读取新密码')
    reset_parser.add_argument('--dry-run', action='store_true', help='只校验，不实际修改')
    reset_parser.add_argument('--yes', action='store_true', help='跳过 RESET 交互确认（自动化慎用）')
    reset_parser.add_argument('--audit-log', default='', help='可选：审计日志 CSV 路径（不含密码）')
    reset_parser.set_defaults(func=cmd_reset)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, 'command', None):
        return cmd_interactive()
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
