#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调度层接线测试：确认「凭据 → 登录 → 下发团体名 → 结果落表」这条链没接错。

不连设备：mock 掉 open_session 与 snmp.apply，只验证参数传递和结果字段。
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from h3c_ops import runner, snmp
from h3c_ops.config import load_config
from h3c_ops.inventory import Device
from h3c_ops.login import Credential, LoginOutcome
from h3c_ops.ssh import AuthError


class FakeSession:
    def __init__(self):
        self.hostname = "SW-Core-01"
        self.closed = False

    def close(self):
        self.closed = True


def make_cfg(tmpdir: Path):
    payload = {
        "credentials": {"username": "netops", "password": "P@ss1234", "candidates": []},
        "snmp": {"read_community": "OpsRead@2026", "acl_number": 0, "acl_sources": []},
    }
    path = tmpdir / "config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return load_config(path)


def make_device():
    return Device(
        row=2, ip="10.0.0.1", username="netops", password="P@ss1234",
        name="SW-Core-01", credential_source="设备清单",
    )


class ProcessDeviceTest(unittest.TestCase):
    def test_credential_override_is_passed_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp))
            device = make_device()
            override = Credential("admin", "Admin@123", source="命令行")
            session = FakeSession()
            outcome = LoginOutcome(session, override, "已提权到 3 级", ["清单凭据不可用"])

            with mock.patch.object(runner, "open_session", return_value=outcome) as opener, \
                 mock.patch.object(
                     snmp, "apply",
                     return_value=snmp.ApplyResult("成功", "团体名已生效", [], 0, True),
                 ) as apply_mock:
                result = runner.process_device(cfg, device, ["snmp"], dry_run=False, credential=override)

            self.assertEqual(opener.call_args.kwargs["override"], override)
            self.assertTrue(result.reachable)
            self.assertEqual(result.login_account, "admin")
            self.assertEqual(result.login_note, "已提权到 3 级")
            self.assertIn("清单凭据不可用", result.warnings)
            self.assertEqual(result.snmp.status, "成功")
            self.assertTrue(session.closed)   # 会话必须关闭
            # 团体名用的是设备行里的值（为空时由 snmp 模块回落到配置）
            self.assertEqual(apply_mock.call_args.args[2], "")

    def test_login_failure_marks_stage_failed_and_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp))
            with mock.patch.object(runner, "open_session", side_effect=AuthError("全部凭据均认证失败")):
                result = runner.process_device(cfg, make_device(), ["snmp"], dry_run=False)

            self.assertFalse(result.reachable)
            self.assertIn("全部凭据均认证失败", result.error)
            self.assertEqual(result.snmp.status, "失败")

    def test_dry_run_flag_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp))
            outcome = LoginOutcome(FakeSession(), Credential("netops", "P@ss1234"))
            with mock.patch.object(runner, "open_session", return_value=outcome), \
                 mock.patch.object(
                     snmp, "apply", return_value=snmp.ApplyResult("预览", "将下发 5 条命令")
                 ) as apply_mock:
                runner.process_device(cfg, make_device(), ["snmp"], dry_run=True)
            self.assertTrue(apply_mock.call_args.kwargs["dry_run"])


if __name__ == "__main__":
    unittest.main()
