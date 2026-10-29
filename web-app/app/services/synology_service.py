"""群晖 DSM 用户管理服务。

本模块只依赖 requests，不依赖 Flask，便于 Web 页面与命令行工具复用。

设计要点：
- 只使用 DSM 官方 Web API，不依赖 SSH，也不要求在 NAS 上安装套件。
- 修改密码前先读取用户当前属性，并通过 ``SYNO.Core.User`` 的 ``set``
  方法原样回传这些属性，避免只传 password 时把描述、邮箱、过期时间等
  字段重置为默认值。
- 密码、SID 只存在于进程内存，不写入数据库、日志或浏览器 Cookie。
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable
from urllib.parse import urlparse

import requests

try:  # urllib3 随 requests 安装，这里做兼容处理
    from urllib3.exceptions import InsecureRequestWarning
except Exception:  # pragma: no cover - 极少数精简环境
    InsecureRequestWarning = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class SynologyError(Exception):
    """群晖操作基础异常。"""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:  # pragma: no cover - 简单委托
        return self.message


class SynologyConnectionError(SynologyError):
    """网络连接、TLS 或响应解析失败。"""


class SynologyAuthError(SynologyError):
    """登录失败。``requires_otp`` 为 True 时表示需要动态验证码。"""

    def __init__(self, message: str, code: int | None = None, requires_otp: bool = False):
        super().__init__(message, code)
        self.requires_otp = requires_otp


class SynologyAPIError(SynologyError):
    """DSM API 返回 success=false。"""


class SynologySessionExpired(SynologyAPIError):
    """DSM 会话失效，需要重新登录。"""


# DSM 核心 API 错误码。登录接口与普通接口共用一部分错误码，
# 这里统一映射为可读中文；登录错误在 _login_error 中单独处理。
API_ERROR_MESSAGES: dict[int, str] = {
    100: "群晖返回未知错误",
    101: "请求参数无效（可能是不支持该 API 版本）",
    102: "群晖上不存在该 API",
    103: "群晖上不存在该 API 方法",
    104: "当前 DSM 版本不支持该 API 版本",
    105: "当前登录账号没有执行该操作的权限",
    106: "DSM 会话已超时，请重新登录",
    107: "DSM 会话被其他登录中断，请重新登录",
    108: "文件上传失败",
    109: "网络连接不稳定或系统繁忙，请稍后重试",
    110: "网络连接不稳定或系统繁忙，请稍后重试",
    111: "网络连接不稳定或系统繁忙，请稍后重试",
    114: "请求缺少必要参数",
    115: "不允许上传文件",
    116: "演示站点不允许该操作",
    117: "网络连接不稳定或系统繁忙，请稍后重试",
    118: "网络连接不稳定或系统繁忙，请稍后重试",
    119: "DSM 会话无效，请重新登录",
    150: "请求来源 IP 与登录 IP 不一致",
}

AUTH_ERROR_MESSAGES: dict[int, str] = {
    400: "账号或密码错误",
    401: "该账号已被停用",
    402: "该账号没有登录权限",
    403: "该账号已启用双重验证，请输入动态验证码",
    404: "动态验证码错误",
    405: "该账号没有登录权限",
    406: "该账号强制要求双重验证，请输入动态验证码",
    407: "来源 IP 已被禁止登录",
    408: "密码已过期，且不允许修改",
    409: "密码已过期",
    410: "必须先修改密码才能登录",
    411: "登录权限不足",
    412: "该账号已被锁定",
}

# 这些错误码表示登录会话已经不可用
SESSION_EXPIRED_CODES = {105, 106, 107, 119}


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return False


def _as_bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "enabled"}:
            return True
        if text in {"0", "false", "no", "off", "disabled"}:
            return False
    return None


def _header_safe(value: Any) -> str:
    """去掉回车换行，避免把用户输入带进 HTTP 头。"""
    return re.sub(r"[\r\n]", "", str(value or "")).strip()


# ---------------------------------------------------------------------------
# URL 与输入校验
# ---------------------------------------------------------------------------


def normalize_base_url(host: str, port: int = 5001, use_https: bool = True) -> tuple[str, str, int]:
    """把用户输入的 NAS 地址规范化为 ``scheme://host:port``。

    支持以下写法：
    - ``192.168.1.10``
    - ``nas.example.com:5001``
    - ``https://nas.example.com:5001``
    - ``[fe80::1]``

    返回 ``(base_url, hostname, port)``。地址中不允许包含路径、查询串、
    用户名密码等，避免把请求发到非预期位置。
    """
    raw = _header_safe(host)
    if not raw:
        raise ValueError("NAS 地址不能为空")
    if any(ch in raw for ch in ("\r", "\n", "\x00")):
        raise ValueError("NAS 地址包含非法字符")

    if "://" not in raw:
        raw = f"{'https' if use_https else 'http'}://{raw}"

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("仅支持 http 或 https 协议")
    if parsed.username or parsed.password:
        raise ValueError("NAS 地址中不能包含用户名或密码")
    if parsed.path not in ("", "/"):
        raise ValueError("NAS 地址不能包含路径，请只填写主机名或 IP")
    if parsed.query or parsed.fragment:
        raise ValueError("NAS 地址不能包含查询参数")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("NAS 地址格式不正确")
    if re.search(r"\s", hostname):
        raise ValueError("NAS 地址不能包含空格")

    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ValueError("NAS 端口格式不正确") from exc

    if parsed_port is None:
        parsed_port = int(port)
    if not 1 <= parsed_port <= 65535:
        raise ValueError("NAS 端口必须在 1-65535 之间")

    # IPv6 需要方括号
    netloc_host = f"[{hostname}]" if ":" in hostname else hostname
    base_url = f"{parsed.scheme}://{netloc_host}:{parsed_port}"
    return base_url, hostname, parsed_port


def host_allowed(hostname: str, allowlist: Iterable[str] | None) -> bool:
    """可选的 NAS 主机白名单。

    - 空配置表示不限制（默认）。
    - ``.corp.example.com`` 形式表示允许该域名及其所有子域名。
    - 其他值按完整主机名/IP 精确匹配（不区分大小写）。
    """
    rules = [str(item).strip().lower() for item in (allowlist or []) if str(item).strip()]
    if not rules:
        return True
    target = str(hostname).strip().lower().rstrip(".")
    for rule in rules:
        rule = rule.rstrip(".")
        if rule.startswith("."):
            suffix = rule[1:]
            if target == suffix or target.endswith("." + suffix):
                return True
        elif target == rule:
            return True
    return False


# ---------------------------------------------------------------------------
# 用户数据规范化
# ---------------------------------------------------------------------------


def _parse_groups(value: Any) -> list[str]:
    """把 groups 字段统一为字符串列表。

    DSM 不同版本可能返回 ``["users", "administrators"]``、``"users"``
    或 ``[{"name": "users"}]``，这里全部兼容。
    """
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                return _parse_groups(json.loads(text))
            except (ValueError, TypeError):
                pass
        return [item.strip() for item in text.split(",") if item.strip()]
    if isinstance(value, dict):
        value = [value]
    if isinstance(value, (list, tuple, set)):
        groups: list[str] = []
        for item in value:
            if isinstance(item, dict):
                name = item.get("name") or item.get("group_name") or item.get("group")
                if name:
                    groups.append(str(name))
            elif item is not None:
                text = str(item).strip()
                if text:
                    groups.append(text)
        # 去重并保持顺序
        return list(dict.fromkeys(groups))
    return []


def _format_last_change(value: Any) -> str | None:
    """把 DSM 的 password_last_change 转为日期字符串。

    文档示例中该字段是“自 1970-01-01 起的天数”（如 19789），
    部分版本也可能返回 Unix 时间戳，这里都兼容。
    """
    if value in (None, "", 0, "0"):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    if number <= 0:
        return None
    try:
        if number < 100000:  # 天数
            return (date(1970, 1, 1) + timedelta(days=number)).isoformat()
        return datetime.fromtimestamp(number).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return str(value)


def normalize_user(raw: dict[str, Any]) -> dict[str, Any]:
    """把 DSM 返回的用户对象规范化，模板与 CLI 共用。"""
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("用户数据缺少 name 字段")

    groups = _parse_groups(raw.get("groups"))
    lower_groups = {item.lower() for item in groups}
    is_admin = bool(lower_groups & {"administrators", "admin"})

    two_factor_raw = raw.get("2fa_status", raw.get("two_factor_auth"))
    two_factor = _as_bool_or_none(two_factor_raw)

    raw_fields = {}
    for key in ("expired", "description", "email", "cannot_chg_passwd", "passwd_never_expire"):
        if key in raw:
            raw_fields[key] = raw[key]

    return {
        "name": name,
        "uid": raw.get("uid"),
        "description": str(raw.get("description") or ""),
        "email": str(raw.get("email") or ""),
        "groups": groups,
        "groups_known": "groups" in raw,
        "is_admin": is_admin,
        "is_guest": name.lower() == "guest",
        "is_builtin": name.lower() in {"admin", "guest"},
        "expired": raw.get("expired"),
        "cannot_chg_passwd": _is_true(raw.get("cannot_chg_passwd")),
        "passwd_never_expire": _is_true(raw.get("passwd_never_expire")),
        "password_last_change": _format_last_change(raw.get("password_last_change")),
        "two_factor": two_factor,
        "two_factor_raw": two_factor_raw,
        # 保存原始字段，改密时原样回传，避免覆盖用户属性。
        # 这里只保留 API 实际返回的键，便于 set_user_password 判断属性是否完整。
        "raw": raw_fields,
    }


def default_password_policy() -> dict[str, Any]:
    """无法读取密码策略时使用的保守默认值。"""
    return {
        "available": False,
        "min_length": 8,
        "min_length_enable": True,
        "mixed_case": True,
        "included_numeric_char": True,
        "included_special_char": False,
        "exclude_username": True,
        "history_num": 0,
        "password_must_change": False,
    }


def normalize_password_policy(data: dict[str, Any]) -> dict[str, Any]:
    strong = data.get("strong_password") if isinstance(data, dict) else None
    strong = strong if isinstance(strong, dict) else {}
    policy = default_password_policy()
    policy["available"] = True
    try:
        policy["min_length"] = max(1, int(strong.get("min_length", 8)))
    except (TypeError, ValueError):
        policy["min_length"] = 8
    policy["min_length_enable"] = _is_true(strong.get("min_length_enable", True))
    policy["mixed_case"] = _is_true(strong.get("mixed_case", True))
    policy["included_numeric_char"] = _is_true(strong.get("included_numeric_char", True))
    policy["included_special_char"] = _is_true(strong.get("included_special_char", False))
    policy["exclude_username"] = _is_true(strong.get("exclude_username", True))
    try:
        policy["history_num"] = max(0, int(strong.get("history_num", 0) or 0))
    except (TypeError, ValueError):
        policy["history_num"] = 0
    policy["password_must_change"] = _is_true(data.get("password_must_change", False))
    return policy


def validate_password(password: str, policy: dict[str, Any], username: str | None = None) -> list[str]:
    """按群晖密码策略校验密码，返回中文错误列表。"""
    errors: list[str] = []
    if not isinstance(password, str) or password == "":
        return ["新密码不能为空"]
    if len(password) > 256:
        errors.append("新密码不能超过 256 个字符")
    min_length = int(policy.get("min_length") or 8)
    if policy.get("min_length_enable", True) and len(password) < min_length:
        errors.append(f"新密码至少需要 {min_length} 个字符")
    if policy.get("mixed_case") and not (
        any(ch.islower() for ch in password) and any(ch.isupper() for ch in password)
    ):
        errors.append("新密码必须同时包含大写和小写字母")
    if policy.get("included_numeric_char") and not any(ch.isdigit() for ch in password):
        errors.append("新密码必须包含数字")
    if policy.get("included_special_char") and not any(not ch.isalnum() for ch in password):
        errors.append("新密码必须包含特殊字符")
    if policy.get("exclude_username") and username and username.lower() in password.lower():
        errors.append("新密码不能包含用户名")
    return errors


# ---------------------------------------------------------------------------
# DSM 客户端
# ---------------------------------------------------------------------------


class SynologyClient:
    """最小化的群晖 DSM Web API 客户端。

    只实现本项目需要的登录、用户扫描、密码策略和改密功能。
    """

    AUTH_API = "SYNO.API.Auth"
    USER_API = "SYNO.Core.User"
    POLICY_API = "SYNO.Core.User.PasswordPolicy"

    DEFAULT_PATHS = {
        AUTH_API: "/webapi/auth.cgi",
        USER_API: "/webapi/entry.cgi",
        POLICY_API: "/webapi/entry.cgi",
    }

    USER_LIST_FIELDS = [
        "description",
        "email",
        "expired",
        "cannot_chg_passwd",
        "passwd_never_expire",
        "password_last_change",
        "groups",
        "2fa_status",
    ]
    USER_LIST_FIELDS_BASIC = [
        "description",
        "email",
        "expired",
        "cannot_chg_passwd",
        "passwd_never_expire",
        "password_last_change",
    ]
    USER_GET_FIELDS = [
        "description",
        "email",
        "expired",
        "cannot_chg_passwd",
        "passwd_never_expire",
        "password_last_change",
    ]

    def __init__(
        self,
        base_url: str,
        verify_ssl: bool = True,
        timeout: float = 20,
        http_session: requests.Session | None = None,
    ):
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("NAS 地址格式不正确")
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = bool(verify_ssl)
        self.timeout = float(timeout)
        self.session = http_session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "OpsManager-SynologyUser/1.0",
                "Accept": "application/json, text/plain, */*",
            }
        )
        self.sid: str | None = None
        self.account: str | None = None
        self._paths = dict(self.DEFAULT_PATHS)
        self._versions: dict[str, int] = {}

    # -- HTTP 基础 ---------------------------------------------------------

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    @staticmethod
    def _encode_params(params: dict[str, Any]) -> dict[str, str]:
        encoded: dict[str, str] = {}
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, bool):
                encoded[key] = "true" if value else "false"
            elif isinstance(value, (list, tuple, dict)):
                encoded[key] = json.dumps(value, ensure_ascii=False)
            else:
                encoded[key] = str(value)
        return encoded

    def _raw_request(
        self,
        path: str,
        params: dict[str, Any],
        *,
        use_get: bool = False,
    ) -> dict[str, Any]:
        url = self._url(path)
        data = self._encode_params(params)
        kwargs: dict[str, Any] = {
            "timeout": self.timeout,
            "verify": self.verify_ssl,
            "allow_redirects": False,
        }
        try:
            if use_get:
                response = self.session.get(url, params=data, **kwargs)
            else:
                response = self.session.post(url, data=data, **kwargs)
        except requests.exceptions.SSLError as exc:
            raise SynologyConnectionError(
                "TLS 证书校验失败。若 NAS 使用自签名证书，请取消勾选“校验 TLS 证书”后重试。"
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise SynologyConnectionError("连接群晖超时，请检查地址、端口和网络连通性。") from exc
        except requests.exceptions.ConnectionError as exc:
            raise SynologyConnectionError(
                "无法连接群晖，请检查地址、端口、HTTPS 设置以及防火墙。"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise SynologyConnectionError(f"请求群晖失败：{exc}") from exc

        if response.status_code in (301, 302, 303, 307, 308):
            location = _header_safe(response.headers.get("Location"))
            raise SynologyConnectionError(
                f"群晖返回了重定向（{response.status_code}），请检查地址/端口"
                + (f"：{location}" if location else "。")
            )
        if response.status_code >= 400:
            raise SynologyConnectionError(
                f"群晖返回 HTTP {response.status_code}，请确认 DSM 地址和端口正确。"
            )

        try:
            body = response.json()
        except ValueError as exc:
            content_type = _header_safe(response.headers.get("Content-Type"))
            raise SynologyConnectionError(
                "群晖返回的不是 JSON 数据，可能不是 DSM 管理端口，或被反向代理拦截。"
                + (f"（Content-Type: {content_type}）" if content_type else "")
            ) from exc
        if not isinstance(body, dict):
            raise SynologyConnectionError("群晖返回的数据格式不正确。")
        return body

    def _raise_api_error(self, body: dict[str, Any], *, auth: bool = False) -> None:
        error = body.get("error") or {}
        try:
            code = int(error.get("code")) if isinstance(error, dict) else int(error)
        except (TypeError, ValueError):
            code = None
        message = (AUTH_ERROR_MESSAGES if auth else API_ERROR_MESSAGES).get(
            code or -1, f"群晖返回错误（错误码 {code}）"
        )
        if auth:
            requires_otp = code in (403, 406)
            raise SynologyAuthError(message, code=code, requires_otp=requires_otp)
        if code in SESSION_EXPIRED_CODES:
            raise SynologySessionExpired(message, code=code)
        raise SynologyAPIError(message, code=code)

    def _call(
        self,
        api: str,
        params: dict[str, Any],
        *,
        use_get: bool = False,
        auth: bool = False,
        path: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"api": api, **params}
        if self.sid and not auth:
            payload["_sid"] = self.sid
        body = self._raw_request(path or self._paths.get(api, "/webapi/entry.cgi"), payload, use_get=use_get)
        if not body.get("success"):
            self._raise_api_error(body, auth=auth)
        data = body.get("data")
        return data if isinstance(data, dict) else {"data": data}

    # -- 登录 -------------------------------------------------------------

    def discover(self) -> dict[str, Any]:
        """查询 DSM API 信息，更新实际路径和版本（失败不阻断登录）。"""
        params = {
            "api": "SYNO.API.Info",
            "version": 1,
            "method": "query",
            "query": f"{self.AUTH_API},{self.USER_API},{self.POLICY_API}",
        }
        body = self._raw_request("/webapi/query.cgi", params, use_get=True)
        if not body.get("success"):
            return {}
        data = body.get("data") or {}
        if not isinstance(data, dict):
            return {}
        for api, info in data.items():
            if not isinstance(info, dict):
                continue
            path = info.get("path")
            if isinstance(path, str) and path:
                self._paths[api] = path if path.startswith("/") else "/" + path
            try:
                self._versions[api] = int(info.get("maxVersion") or 1)
            except (TypeError, ValueError):
                self._versions[api] = 1
        return data

    def login(self, account: str, password: str, otp_code: str | None = None) -> str:
        """登录 DSM，返回 SID。"""
        account = _header_safe(account)
        if not account or not password:
            raise SynologyAuthError("登录账号和密码不能为空")

        # 先探测 API 路径；探测失败时仍使用默认路径继续尝试。
        # 连接/TLS 错误直接抛出，避免对不可达主机重复等待超时。
        try:
            self.discover()
        except SynologyConnectionError:
            raise
        except SynologyError:
            pass

        otp_code = _header_safe(otp_code) or None
        auth_path = self._paths.get(self.AUTH_API, "/webapi/auth.cgi")
        last_error: SynologyAuthError | None = None
        for version in (6, 5, 3, 1):
            params = {
                "api": self.AUTH_API,
                "version": version,
                "method": "login",
                "account": account,
                "passwd": password,
                "session": "OpsManager",
                "format": "sid",
            }
            if otp_code:
                params["otp_code"] = otp_code
            try:
                data = self._call(self.AUTH_API, params, auth=True, path=auth_path)
            except SynologyAuthError as exc:
                # 只有“版本不支持”才降级重试，避免密码错误时重复请求
                if exc.code == 104:
                    last_error = exc
                    continue
                raise
            sid = data.get("sid")
            if not sid:
                raise SynologyAuthError("登录响应中没有会话 ID，请确认 DSM 版本和账号权限。")
            self.sid = str(sid)
            self.account = account
            return self.sid

        raise last_error or SynologyAuthError("无法与当前 DSM 版本建立登录会话")

    def logout(self) -> None:
        """注销 DSM 会话；失败不影响本地清理。"""
        if not self.sid:
            return
        try:
            self._call(
                self.AUTH_API,
                {
                    "api": self.AUTH_API,
                    "version": 1,
                    "method": "logout",
                    "session": "OpsManager",
                    "_sid": self.sid,
                },
                auth=True,
                path=self._paths.get(self.AUTH_API, "/webapi/auth.cgi"),
            )
        except SynologyError:
            pass
        finally:
            self.sid = None

    # -- 用户 -------------------------------------------------------------

    def _list_users_with_fields(self, fields: list[str]) -> list[dict[str, Any]]:
        data = self._call(
            self.USER_API,
            {
                "version": 1,
                "method": "list",
                "type": "local",
                "offset": 0,
                "limit": -1,
                "sort_by": "name",
                "sort_direction": "ASC",
                "additional": fields,
            },
            use_get=True,
        )
        users = data.get("users") if isinstance(data, dict) else None
        if not isinstance(users, list):
            raise SynologyAPIError("群晖返回的用户列表格式不正确")
        return [normalize_user(item) for item in users if isinstance(item, dict)]

    def list_users(self) -> list[dict[str, Any]]:
        """扫描全部本地用户。

        部分 DSM 版本不支持 groups/2fa_status 字段，此时自动降级到基础
        字段，保证扫描仍能完成。降级顺序保留 groups，尽量不丢失管理员识别。
        """
        field_sets = (
            self.USER_LIST_FIELDS,
            [field for field in self.USER_LIST_FIELDS if field != "2fa_status"],
            self.USER_LIST_FIELDS_BASIC,
            [],
        )
        last_error: SynologyAPIError | None = None
        for fields in field_sets:
            try:
                return self._list_users_with_fields(fields)
            except SynologyAPIError as exc:
                if exc.code not in {101, 103, 104, 114}:
                    raise
                last_error = exc
        raise last_error or SynologyAPIError("群晖用户列表接口不可用")

    def get_user(self, name: str) -> dict[str, Any]:
        """读取单个用户的当前属性。

        若旧版 DSM 不支持 additional 字段，则降级为不带 additional 的
        请求。缺少过期时间等关键属性时，改密函数会安全中止。
        """
        for fields in (self.USER_GET_FIELDS, []):
            try:
                data = self._call(
                    self.USER_API,
                    {
                        "version": 1,
                        "method": "get",
                        "type": "local",
                        "name": name,
                        "additional": fields,
                    },
                    use_get=True,
                )
                break
            except SynologyAPIError as exc:
                if fields and exc.code in {101, 103, 104, 114}:
                    continue
                raise
        else:  # pragma: no cover - 上面的循环要么 break 要么 raise
            raise SynologyAPIError(f"无法读取用户 {name}")

        users = data.get("users") if isinstance(data, dict) else None
        if not users or not isinstance(users, list) or not isinstance(users[0], dict):
            raise SynologyAPIError(f"未找到用户 {name}")
        return normalize_user(users[0])

    def get_password_policy(self) -> dict[str, Any]:
        """读取全局密码策略；读取失败时返回保守默认值。"""
        try:
            data = self._call(
                self.POLICY_API,
                {"version": 1, "method": "get"},
                use_get=True,
            )
            return normalize_password_policy(data)
        except SynologyAPIError as exc:
            # 权限不足或 API 不存在不应阻止用户扫描，但会让前端使用默认策略。
            if exc.code in {102, 103, 104, 105}:
                return default_password_policy()
            raise
        except SynologyError:
            return default_password_policy()

    def set_user_password(
        self,
        name: str,
        password: str,
        current: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """重置指定用户的密码，并保留其现有账号属性。

        关键安全点：DSM 的 ``SYNO.Core.User.set`` 是一个“整体更新”接口。
        如果只提交 name/password，未提交的 description、email、expired、
        cannot_chg_passwd、passwd_never_expire 可能被重置。因此这里先
        ``get`` 当前值，再原样带回。

        ``current`` 允许调用方传入刚刚读取的用户数据，避免重复请求。
        """
        current = current or self.get_user(name)
        if current["name"] != name:
            raise SynologyAPIError("群晖返回的用户名与请求不一致，已中止改密")

        required = ("expired", "cannot_chg_passwd", "passwd_never_expire")
        missing = [key for key in required if key not in current["raw"]]
        if missing:
            raise SynologyAPIError(
                "无法读取该用户的完整属性（" + ", ".join(missing) + "），为避免覆盖账号设置已中止改密"
            )

        raw = current["raw"]
        params = {
            "version": 1,
            "method": "set",
            "name": current["name"],
            "new_name": current["name"],
            "password": password,
            "description": raw.get("description") or "",
            "email": raw.get("email") or "",
            "expired": raw.get("expired") or "never",
            "cannot_chg_passwd": _is_true(raw.get("cannot_chg_passwd")),
            "passwd_never_expire": _is_true(raw.get("passwd_never_expire")),
            "notify_by_email": False,
            "send_password": False,
        }
        data = self._call(self.USER_API, params, use_get=False)
        return data


# ---------------------------------------------------------------------------
# 进程内会话存储
# ---------------------------------------------------------------------------


@dataclass
class NasSession:
    """一个已登录的 NAS 会话。

    ``client`` 内含 DSM SID，仅保存在当前进程内存中。浏览器只拿到一个
    随机 token，不会接触 SID 或管理员密码。
    """

    token: str
    client: SynologyClient
    host: str
    base_url: str
    account: str
    users: list[dict[str, Any]]
    policy: dict[str, Any]
    scan_at: datetime
    csrf_token: str
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    batch_result: dict[str, Any] | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.created_at)

    def set_batch_result(self, result: dict[str, Any] | None) -> None:
        with self.lock:
            self.batch_result = result

    def get_batch_result(self) -> dict[str, Any] | None:
        with self.lock:
            return self.batch_result


class NasSessionStore:
    """线程安全的会话存储。

    默认适用于单进程部署（Flask 开发服务器 / gunicorn 单 worker）。
    多进程部署需要改为 Redis 等共享存储；否则请求落到不同 worker 时会
    要求重新登录。该限制已写入 README。
    """

    def __init__(self, ttl: int = 1800, max_sessions: int = 100):
        self.ttl = max(60, int(ttl))
        self.max_sessions = max(1, int(max_sessions))
        self._sessions: dict[str, NasSession] = {}
        self._lock = threading.RLock()

    def configure(self, ttl: int | None = None, max_sessions: int | None = None) -> None:
        if ttl is not None:
            self.ttl = max(60, int(ttl))
        if max_sessions is not None:
            self.max_sessions = max(1, int(max_sessions))

    def _purge_locked(self) -> None:
        now = time.time()
        expired = [
            token
            for token, item in self._sessions.items()
            if now - item.last_seen > self.ttl
        ]
        for token in expired:
            self._sessions.pop(token, None)

    def create(
        self,
        *,
        client: SynologyClient,
        host: str,
        base_url: str,
        account: str,
        users: list[dict[str, Any]],
        policy: dict[str, Any],
    ) -> NasSession:
        with self._lock:
            self._purge_locked()
            if len(self._sessions) >= self.max_sessions:
                oldest = min(self._sessions.values(), key=lambda item: item.last_seen)
                self._sessions.pop(oldest.token, None)
            token = secrets.token_urlsafe(32)
            item = NasSession(
                token=token,
                client=client,
                host=host,
                base_url=base_url,
                account=account,
                users=users,
                policy=policy,
                scan_at=datetime.now(),
                csrf_token=secrets.token_urlsafe(32),
            )
            self._sessions[token] = item
            return item

    def get(self, token: str | None) -> NasSession | None:
        if not token:
            return None
        with self._lock:
            item = self._sessions.get(token)
            if not item:
                return None
            if time.time() - item.last_seen > self.ttl:
                self._sessions.pop(token, None)
                return None
            item.last_seen = time.time()
            return item

    def drop(self, token: str | None, *, logout: bool = True) -> None:
        if not token:
            return
        with self._lock:
            item = self._sessions.pop(token, None)
        if item and logout:
            try:
                item.client.logout()
            except SynologyError:
                pass

    def count(self) -> int:
        with self._lock:
            self._purge_locked()
            return len(self._sessions)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


# 全局单例：由应用工厂按配置调整 TTL
nas_session_store = NasSessionStore()


def csv_safe(value: Any) -> str:
    """防止 CSV 公式注入。"""
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text
