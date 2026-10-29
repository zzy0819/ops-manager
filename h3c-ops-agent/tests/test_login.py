#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""登录策略单测：多凭据回落、去重、提权告警。

全部不连真实设备：把 login.make_session 换成假会话，只验证"选哪个账号、试几次"。
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from h3c_ops import login
from h3c_ops.config import load_config
from h3c_ops.inventory import Device
from h3c_ops.login import Credential, build_candidates, open_session
from h3c_ops.ssh import AuthError, ConnectError


class FakeSession:
    """按账号密码决定登录成功与否，并记录尝试次数。"""

    registry = {}
    attempts = []

    def __init__(self, username, password, secret=""):
        self.username = username
        self.password = password
        self.secret = secret
        self.hostname = "SW1"
        self.closed = False
        self.elevated = False

    def connect(self):
        FakeSession.attempts.append(self.username)
        outcome = FakeSession.registry.get((self.username, self.password), "auth_fail")
        if outcome == "auth_fail":
            raise AuthError("认证失败：用户名/密码错误")
        if outcome == "network":
            raise ConnectError("连接超时")
        return None

    def elevate(self, level=3):
        self.elevated = True
        return FakeSession.registry.get(("elevate", self.username), (True, "已提权到 3 级"))

    def close(self):
        self.closed = True


def make_cfg(tmpdir: Path, candidates=None, username="", password=""):
    payload = {
        "credentials": {
            "username": username,
            "password": password,
            "candidates": candidates or [],
        }
    }
    path = tmpdir / "config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return load_config(path)


def make_device(username="netops", password="P@ss1234", secret=""):
    return Device(
        row=2, ip="10.0.0.1", username=username, password=password,
        secret=secret, name="SW-Core-01", credential_source="设备清单",
    )


class CandidateBuildTest(unittest.TestCase):
    def test_order_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(
                Path(tmp),
                candidates=[
                    {"username": "admin", "password": "Admin@123"},
                    {"username": "netops", "password": "P@ss1234"},  # 与清单重复
                ],
                username="h3c",
                password="H3C@1234",
            )
            device = make_device()
            # 清单里没有密码时会先回落到配置默认，这里模拟"清单有凭据"
            creds = build_candidates(cfg, device)
            self.assertEqual([c.username for c in creds], ["netops", "admin", "h3c"])

    def test_override_goes_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp))
            device = make_device()
            creds = build_candidates(cfg, device, Credential("tmp", "Tmp@1234", source="命令行"))
            self.assertEqual(creds[0].source, "命令行")
            self.assertEqual(creds[0].username, "tmp")

    def test_override_is_exclusive(self):
        """命令行给了账号就不该再回落到清单账号，否则现场容易误判"到底用的哪个号"。"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp), candidates=[{"username": "admin", "password": "Admin@123"}])
            creds = build_candidates(
                cfg, make_device(), Credential("tmp", "Tmp@1234", source="命令行")
            )
            self.assertEqual([c.username for c in creds], ["tmp"])

    def test_list_form_candidates_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp), candidates=[["admin", "Admin@123"], ["ops", "Ops@1234", "S3cret"]])
            self.assertEqual([c["username"] for c in cfg.section("credentials")["candidates"]],
                             ["admin", "ops"])
            self.assertEqual(cfg.section("credentials")["candidates"][1]["secret"], "S3cret")

    def test_no_credential_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp))
            device = Device(row=2, ip="10.0.0.1", username="", password="")
            with self.assertRaises(AuthError):
                open_session(cfg, device)


class OpenSessionTest(unittest.TestCase):
    def setUp(self):
        FakeSession.registry = {}
        FakeSession.attempts = []
        self.patcher = mock.patch.object(login, "make_session", self._fake_factory)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    @staticmethod
    def _fake_factory(cfg, device, credential):
        return FakeSession(credential.username, credential.password, credential.secret)

    def test_falls_back_to_second_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp), candidates=[{"username": "admin", "password": "Admin@123"}])
            FakeSession.registry[("admin", "Admin@123")] = "ok"
            outcome = open_session(cfg, make_device())
            self.assertEqual(outcome.account, "admin")
            self.assertEqual(FakeSession.attempts, ["netops", "admin"])
            self.assertTrue(any("已自动改用" in w for w in outcome.warnings))

    def test_each_account_tried_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(
                Path(tmp),
                candidates=[
                    {"username": "admin", "password": "Admin@123"},
                    {"username": "admin", "password": "Admin@123"},  # 重复项应被去掉
                ],
            )
            with self.assertRaises(AuthError) as ctx:
                open_session(cfg, make_device())
            self.assertEqual(FakeSession.attempts, ["netops", "admin"])  # 没有第二次 admin
            self.assertIn("停止重试", str(ctx.exception))

    def test_network_error_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp), candidates=[{"username": "admin", "password": "Admin@123"}])
            FakeSession.registry[("netops", "P@ss1234")] = "network"
            with self.assertRaises(ConnectError):
                open_session(cfg, make_device())
            self.assertEqual(FakeSession.attempts, ["netops"])  # 网络问题换账号没意义

    def test_elevate_failure_becomes_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp))
            device = make_device(secret="WrongSecret")
            FakeSession.registry[("netops", "P@ss1234")] = "ok"
            FakeSession.registry[("elevate", "netops")] = (False, "super 提权失败: 密码错误")
            outcome = open_session(cfg, device)
            self.assertTrue(outcome.session.elevated)
            self.assertIn("提权失败", " ".join(outcome.warnings))

    def test_no_secret_skips_elevate(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp))
            FakeSession.registry[("netops", "P@ss1234")] = "ok"
            outcome = open_session(cfg, make_device(secret=""))
            self.assertFalse(outcome.session.elevated)
            self.assertEqual(outcome.warnings, [])


if __name__ == "__main__":
    unittest.main()
