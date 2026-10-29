#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""登录策略：按"清单里的账号密码"自动登录，多套凭据逐级回落。

凭据优先级（同一账号密码只试一次，避免触发设备账号锁定）：
    0. 命令行 --user/--password 指定 → 只用它，不再回落到清单（避免"以为在试 A 其实试了 B"）
    1. 设备清单该行的 用户名/密码
    2. config.json 的 credentials.candidates 候选账号（可配多套）
    3. config.json 的 credentials.username/password（兜底）

认证失败会换下一个账号；网络/协议类错误直接抛，不做无意义的换账号重试。
super 密码（低权限账号）在登录后自动提权，失败只记告警不中断。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from .inventory import Device
from .ssh import AuthError, H3CError, H3CSession

log = logging.getLogger("h3c_ops.login")


@dataclass
class Credential:
    username: str
    password: str = field(repr=False)
    secret: str = field(default="", repr=False)
    source: str = "设备清单"

    def masked(self) -> str:
        return f"{self.username}（{self.source}）"


@dataclass
class LoginOutcome:
    session: H3CSession
    credential: Credential
    privilege_note: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def account(self) -> str:
        return self.credential.username


def build_candidates(
    cfg, device: Device, override: Optional[Credential] = None
) -> List[Credential]:
    """按优先级拼出本次要尝试的凭据列表（已去重）。"""
    raw: List[Credential] = []

    if override and override.username and override.password:
        # 命令行显式给了账号就只用它：这是"应急改用一个账号"，不该再悄悄试别的
        return [override]

    if device.username and device.password:
        raw.append(
            Credential(
                username=device.username,
                password=device.password,
                secret=device.secret,
                source=device.credential_source or "设备清单",
            )
        )

    for item in cfg.section("credentials").get("candidates") or []:
        raw.append(
            Credential(
                username=item.get("username", ""),
                password=item.get("password", ""),
                secret=item.get("secret", "") or device.secret,
                source="配置候选账号",
            )
        )

    section = cfg.section("credentials")
    if section.get("username") and section.get("password"):
        raw.append(
            Credential(
                username=section["username"],
                password=section["password"],
                secret=section.get("secret", "") or device.secret,
                source="配置默认",
            )
        )

    seen = set()
    unique: List[Credential] = []
    for cred in raw:
        if not cred.username or not cred.password:
            continue
        key = (cred.username, cred.password)
        if key in seen:
            continue
        seen.add(key)
        unique.append(cred)
    return unique


def make_session(cfg, device: Device, credential: Credential) -> H3CSession:
    return H3CSession(
        ip=device.ip,
        username=credential.username,
        password=credential.password,
        port=device.port,
        secret=credential.secret or device.secret,
        connect_timeout=int(cfg.get("global.connect_timeout", 15)),
        command_timeout=int(cfg.get("global.command_timeout", 30)),
        save_timeout=int(cfg.get("global.save_timeout", 180)),
    )


def open_session(
    cfg,
    device: Device,
    override: Optional[Credential] = None,
    do_elevate: bool = True,
) -> LoginOutcome:
    """登录一台设备并（可选）提权，返回可用的会话。

    全部凭据认证失败时抛 AuthError；网络/协议类错误按原样抛出。
    """
    candidates = build_candidates(cfg, device, override)
    if not candidates:
        raise AuthError(
            "没有可用凭据：请在设备清单填用户名/密码，"
            "或在 config.json 配 credentials.username/password（或 candidates 候选账号）"
        )

    failed: List[str] = []
    last_auth_error: Optional[AuthError] = None

    for credential in candidates:
        session = make_session(cfg, device, credential)
        try:
            session.connect()
        except AuthError as e:
            session.close()
            last_auth_error = e
            failed.append(f"{credential.username}（{credential.source}）")
            if len(candidates) > 1:
                log.warning(
                    "[登录] %s(%s) 账号 %s 认证失败，换下一个凭据",
                    device.label, device.ip, credential.username,
                )
            continue
        except H3CError:
            session.close()
            raise

        warnings: List[str] = []
        if failed:
            warnings.append(f"清单凭据不可用，已自动改用账号 {credential.username} 登录")
            log.warning(
                "[登录] %s(%s) 改用账号 %s（%s）",
                device.label, device.ip, credential.username, credential.source,
            )

        privilege_note = ""
        if do_elevate and (credential.secret or device.secret):
            ok, privilege_note = session.elevate()
            if not ok:
                warnings.append(privilege_note)
                log.warning("[提权] %s(%s) %s", device.label, device.ip, privilege_note)

        log.info(
            "[登录] %s(%s) 成功，账号 %s（%s）%s",
            session.hostname or device.label, device.ip,
            credential.username, credential.source,
            f"，{privilege_note}" if privilege_note else "",
        )
        return LoginOutcome(session, credential, privilege_note, warnings)

    raise AuthError(
        f"全部凭据均认证失败（已尝试 {len(candidates)} 个账号：{'、'.join(failed)}）。"
        "为避免设备锁定，已停止重试，请核对密码或账号权限"
    ) from last_auth_error
