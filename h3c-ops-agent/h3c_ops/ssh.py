#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""华三（Comware V5/V7）交互式 SSH 会话封装。

为什么自己写而不用 netmiko：
    本仓库共享虚拟环境里只有 paramiko，为少装一个依赖，这里用
    invoke_shell + 精确提示符匹配实现，关键点：
      * 登录后先关分页（screen-length disable），避免 ---- More ---- 卡住
      * 提示符正则由实际主机名动态生成，不会误判 [Y/N] / [flash:/startup.cfg]
      * 认证失败不重试（防止触发设备账号锁定），只有网络类错误才重试
      * config 模式统一下发 + 自动退出 + 错误行检测
"""
from __future__ import annotations

import codecs
import logging
import re
import socket
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import paramiko

log = logging.getLogger("h3c_ops.ssh")

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][B0]")
MORE_RE = re.compile(r"-{2,}\s*More\s*-{2,}|--More--", re.IGNORECASE)
GENERIC_PROMPT = re.compile(r"([<\[][^<>\[\]\r\n]{1,64}[>\]])")
MAX_BUFFER = 48 * 1024 * 1024  # 单条命令输出上限，防止异常设备打爆内存

# Comware 报错前缀（小写匹配）
ERROR_MARKERS = (
    "% unrecognized command",
    "% unknown command",
    "% wrong parameter",
    "% incomplete command",
    "% too many parameters",
    "% invalid input",
    "% permission denied",
    "% ambiguous command",
    "% not enough parameters",
    "% invalid command",
    "% cannot",
)
# 这些是"已存在/无变化"类提示，不算失败
WARN_MARKERS = ("already exists", "has been configured", "no change", "the same")

SAVE_OK = ("successfully", "saved the current configuration", "save configuration successfully")
SAVE_FAIL = ("failed", "error", "not permitted", "permission denied", "no space", "insufficient")

# save 交互：老版本会先问是否继续，再问文件名
SAVE_QUESTION_RE = re.compile(r"\[y/n\]|\(y/n\)|continue\?|are you sure", re.IGNORECASE)
SAVE_FILENAME_RE = re.compile(
    r"input the file name|to leave the existing filename|please input the file name",
    re.IGNORECASE,
)


class H3CError(Exception):
    """所有设备交互异常的基类。"""


class ConnectError(H3CError):
    """TCP/SSH 层无法建立连接。"""


class AuthError(H3CError):
    """账号或密码错误。"""


class PromptError(H3CError):
    """无法识别提示符（大概率不是华三设备或 CLI 未就绪）。"""


class CommandError(H3CError):
    """命令执行返回错误。"""

    def __init__(self, command: str, output: str):
        self.command = command
        self.output = output
        super().__init__(f"命令执行失败: {command} → {shorten(output, 180)}")


class CommandTimeout(H3CError):
    """等待命令回显超时。"""

    def __init__(self, command: str, partial: str = ""):
        self.command = command
        self.partial = partial
        super().__init__(f"等待回显超时: {command}")


def shorten(text: str, limit: int = 200) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def find_error(output: str) -> Optional[str]:
    """返回命中的错误提示行，没有则 None。"""
    lowered = (output or "").lower()
    if any(warn in lowered for warn in WARN_MARKERS):
        # 命中"已存在"类提示时再精确确认没有真正的报错
        for line in (output or "").splitlines():
            line_low = line.lower()
            if any(mark in line_low for mark in ERROR_MARKERS) and "already exists" not in line_low:
                return line.strip()
        return None
    for line in (output or "").splitlines():
        line_low = line.lower()
        if any(mark in line_low for mark in ERROR_MARKERS):
            return line.strip()
    return None


@dataclass
class SaveResult:
    ok: bool
    confirmed: bool
    detail: str


class H3CSession:
    """一台设备的会话，with 语句使用。"""

    def __init__(
        self,
        ip: str,
        username: str,
        password: str,
        port: int = 22,
        secret: str = "",
        connect_timeout: int = 15,
        command_timeout: int = 30,
        save_timeout: int = 180,
    ):
        self.ip = ip
        self.port = port
        self.username = username
        self.password = password
        self.secret = secret
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self.save_timeout = save_timeout

        self.client: Optional[paramiko.SSHClient] = None
        self.chan: Optional[paramiko.Channel] = None
        self.hostname = ""
        self.prompt_re = re.compile(r"[<\[][^<>\[\]\r\n]{1,64}[>\]][ ]?$")
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")

    # ------------------------------------------------------------ 生命周期 --
    def __enter__(self) -> "H3CSession":
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def connect(self) -> None:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=self.ip,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=self.connect_timeout,
                banner_timeout=self.connect_timeout,
                auth_timeout=self.connect_timeout,
                look_for_keys=False,
                allow_agent=False,
            )
        except paramiko.AuthenticationException as e:
            client.close()
            raise AuthError(
                "认证失败：用户名/密码错误，或该账号无 SSH 权限（已停止重试以避免账号被锁）"
            ) from e
        except paramiko.BadHostKeyException as e:
            client.close()
            raise ConnectError(f"主机密钥校验失败: {e}") from e
        except (socket.timeout, TimeoutError) as e:
            client.close()
            raise ConnectError(f"连接超时（{self.connect_timeout}s），请检查路由/ACL/防火墙") from e
        except (paramiko.SSHException, OSError) as e:
            client.close()
            hint = ""
            if "no matching" in str(e).lower() or "kex" in str(e).lower():
                hint = "（SSH 算法协商失败，设备端算法过旧，需放开 KEX/加密算法）"
            raise ConnectError(f"SSH 连接失败: {shorten(str(e))}{hint}") from e

        self.client = client
        try:
            self.chan = client.invoke_shell(width=512, height=200)
            self.chan.settimeout(0.5)
            prefetched = self._settle()
            self._detect_hostname(prefetched)
            self._disable_paging()
            self._ensure_user_view()
        except H3CError:
            self.close()
            raise
        except Exception as e:  # noqa: BLE001
            self.close()
            raise ConnectError(f"建立交互式会话失败: {shorten(str(e))}") from e

    def close(self) -> None:
        for closer in (
            lambda: self.chan and self.chan.close(),
            lambda: self.client and self.client.close(),
        ):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass
        self.chan = None
        self.client = None

    # ------------------------------------------------------------ 底层读写 --
    def _settle(self, seconds: float = 1.0) -> str:
        """读取登录 banner（可能连提示符一起读到），返回读到的文本。"""
        assert self.chan is not None
        collected = ""
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.chan.recv_ready():
                chunk = self.chan.recv(65535)
                if not chunk:
                    break
                collected += self._decoder.decode(chunk)
                deadline = time.time() + 0.4  # 有新数据就再等一会儿
            else:
                time.sleep(0.05)
        return collected

    def _drain(self) -> None:
        if not self.chan:
            return
        for _ in range(3):
            if not self.chan.recv_ready():
                return
            self.chan.recv(65535)

    def _read(self, timeout: float, prompt_re: re.Pattern, more: bool = True) -> str:
        assert self.chan is not None
        deadline = time.time() + timeout
        buffer = ""
        while True:
            if self.chan.recv_ready():
                chunk = self.chan.recv(65535)
                if not chunk:
                    raise H3CError("连接被设备关闭（可能触发了登录超时或最大会话数限制）")
                buffer += self._decoder.decode(chunk)
                if len(buffer) > MAX_BUFFER:
                    raise H3CError("命令输出超过 48MB 上限，已中止")
                if prompt_re.search(buffer.rstrip()[-160:] or ""):
                    return buffer
                if more and MORE_RE.search(buffer[-160:]):
                    self.chan.send(" ")
                    buffer = MORE_RE.sub("", buffer)
                    continue
            else:
                if time.time() > deadline:
                    return buffer  # 交由调用方判断是否真的超时
                time.sleep(0.05)

    def _clean(self, raw: str, command: str) -> str:
        text = strip_ansi(raw).replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        if lines and command and command.strip() and command.strip() in lines[0]:
            lines = lines[1:]
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and self.prompt_re.match(lines[-1].strip()):
            lines.pop()
        return "\n".join(line.rstrip() for line in lines).strip("\n")

    # ------------------------------------------------------------ 提示符 --
    def _read_prompt_token(self, timeout: float = 20, prefetched: str = "") -> str:
        """读取直到出现提示符，返回 '<name>' 或 '[name...]'；超时返回空串。"""
        assert self.chan is not None
        buffer = prefetched

        def find(text: str) -> str:
            match = GENERIC_PROMPT.search(strip_ansi(text)[-300:])
            return match.group(0) if match else ""

        token = find(buffer)
        if token:
            return token

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.chan.recv_ready():
                chunk = self.chan.recv(65535)
                if not chunk:
                    raise H3CError("连接被设备关闭")
                buffer += self._decoder.decode(chunk)
                token = find(buffer)
                if token:
                    return token
            else:
                time.sleep(0.05)
        return ""

    def _detect_hostname(self, prefetched: str = "") -> None:
        token = self._read_prompt_token(20, prefetched)
        if not token:
            raise PromptError("登录后未识别到设备提示符（可能不是华三设备，或登录后有多余交互）")

        if token.startswith("["):
            # 登录后落在系统视图：先用当前 token 当临时提示符退回用户视图，再重新识别
            self.prompt_re = re.compile(re.escape(token) + r"\s*$")
            self._prompt = token
            try:
                self.chan.send("return\n")
                token = self._read_prompt_token(15) or token
            except H3CError:
                pass

        name = token[1:-1].strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,63}", name):
            raise PromptError(f"设备提示符异常 {token!r}：无法解析主机名")
        self.hostname = name
        self._prompt = f"<{name}>"
        self._build_prompt_re(name)

    def _build_prompt_re(self, name: str) -> None:
        escaped = re.escape(name)
        self.prompt_re = re.compile(rf"(?:<{escaped}>|\[{escaped}(?:-[^\]\r\n]*)?\])\s*$")

    def _disable_paging(self) -> None:
        for command in ("screen-length disable", "screen-length 0 temporary"):
            try:
                output = self.send(command, timeout=15)
            except H3CError:
                continue
            if not find_error(output):
                return
        log.debug("%s 关闭分页未成功，遇到 More 时仍会自动翻页", self.ip)

    def _ensure_user_view(self) -> None:
        if self.current_prompt.startswith("["):
            self.send("return", timeout=15)

    @property
    def current_prompt(self) -> str:
        """最近一次读到的提示符（用于判断当前视图）。"""
        return getattr(self, "_prompt", f"<{self.hostname}>")

    def _update_prompt(self, raw: str) -> None:
        """从原始回显尾部取提示符，用来判断当前处于用户视图还是系统视图。"""
        for line in reversed(strip_ansi(raw).rstrip().split("\n")):
            line = line.strip()
            if line and self.prompt_re.match(line):
                self._prompt = line
                return

    # ------------------------------------------------------------ 命令执行 --
    def send(self, command: str, timeout: Optional[float] = None, check: bool = False) -> str:
        """发送一条命令（自动带回车），返回去掉回显与提示符后的输出。"""
        if not self.chan:
            raise H3CError("会话未建立")
        self._drain()
        self.chan.send(command + "\n")
        raw = self._read(timeout or self.command_timeout, self.prompt_re)
        output = self._clean(raw, command)
        self._update_prompt(raw)

        if not self.prompt_re.search(strip_ansi(raw).rstrip()[-160:]):
            err = find_error(output)
            if err:
                raise CommandError(command, err)
            raise CommandTimeout(command, output)

        if check:
            err = find_error(output)
            if err:
                raise CommandError(command, err)
        return output

    def send_safe(self, command: str, timeout: Optional[float] = None) -> Tuple[str, Optional[str]]:
        """不抛异常版本：返回 (输出, 错误信息)。用于巡检这类"失败也要继续"的场景。

        注意：命令回显里的 % Unrecognized / % Wrong parameter 也会作为错误返回，
        由调用方决定是忽略（可选命令）还是记入报告。
        """
        try:
            output = self.send(command, timeout=timeout)
        except CommandTimeout as e:
            return e.partial, f"命令超时: {command}"
        except CommandError as e:
            return self._safe_output(e), str(e)
        except H3CError as e:
            return "", str(e)
        return output, find_error(output)

    @staticmethod
    def _safe_output(error: "CommandError") -> str:
        return getattr(error, "output", "") or ""

    # ------------------------------------------------------------ 配置模式 --
    def enter_config(self) -> None:
        self.send("system-view", timeout=20)
        if not self.current_prompt.startswith("["):
            raise ConfigModeError("无法进入系统视图（账号权限不足？）")

    def leave_config(self) -> None:
        try:
            self.send("return", timeout=20)
        except H3CError:
            pass

    def config(self, commands: Iterable[str], stop_on_error: bool = True) -> List[Tuple[str, str, Optional[str]]]:
        """在系统视图下批量下发，返回 [(命令, 输出, 错误)]，退出时必定 return。"""
        results: List[Tuple[str, str, Optional[str]]] = []
        self.enter_config()
        try:
            for command in commands:
                if not command or command.strip().startswith("#"):
                    continue
                try:
                    output = self.send(command, timeout=45)
                    error = find_error(output)
                except CommandTimeout as e:
                    output, error = e.partial, f"命令超时: {command}"
                results.append((command, output, error))
                if error and stop_on_error:
                    raise CommandError(command, f"{error}（已在命令 {command} 处停止下发）")
        finally:
            self.leave_config()
        return results

    # ------------------------------------------------------------ 保存配置 --
    def save(self, timeout: Optional[float] = None) -> SaveResult:
        """save force，并兼容老版本的 [Y/N]、文件名确认交互。"""
        if not self.chan:
            raise H3CError("会话未建立")
        timeout = timeout or self.save_timeout
        self._drain()
        self.chan.send("save force\n")
        deadline = time.time() + timeout
        full = ""      # 全量回显，用于最终判定
        pending = ""   # 尚未应答的部分
        answered = 0
        while time.time() < deadline:
            if self.chan.recv_ready():
                chunk = strip_ansi(self._decoder.decode(self.chan.recv(65535)))
                full += chunk
                pending += chunk
                if answered < 5:
                    # 只认回显末尾的提问，避免同一条回显里 "Continue? [Y/N]" 被应答两次
                    tail_start = max(0, len(pending) - 160)
                    tail = pending[tail_start:]
                    fm = SAVE_FILENAME_RE.search(tail)
                    qm = SAVE_QUESTION_RE.search(tail)
                    if fm or qm:
                        if fm and (not qm or fm.start() <= qm.start()):
                            reply, cut = "\n", fm.start()
                        else:
                            reply, cut = "Y\n", qm.start()
                        self.chan.send(reply)
                        pending = pending[: tail_start + cut]
                        answered += 1
                        continue
                if self.prompt_re.search(pending.rstrip()[-160:]):
                    break
            else:
                time.sleep(0.05)
        else:
            return SaveResult(False, False, "保存超时，设备无响应（配置可能仍在写入，请人工核实）")

        text = self._clean(full, "")
        lowered = text.lower()
        if any(mark in lowered for mark in SAVE_FAIL) and not any(ok in lowered for ok in SAVE_OK):
            return SaveResult(False, False, f"设备返回失败: {shorten(text, 180)}")
        if any(ok in lowered for ok in SAVE_OK):
            return SaveResult(True, True, "配置已保存（save force 回显确认）")
        return SaveResult(True, False, f"未在回显中确认保存结果，请人工核实: {shorten(text, 160)}")

    def elevate(self) -> Optional[str]:
        """可选提权（super）。返回 None 表示成功或无需提权。"""
        if not self.secret:
            return None
        output = self.send("super", timeout=15)
        if "assword" in output.lower():
            output = self.send(self.secret, timeout=15)
            if any(word in output.lower() for word in ("incorrect", "invalid", "failed", "denied")):
                return "super 密码错误，无法提权"
        return None


class ConfigModeError(H3CError):
    pass
