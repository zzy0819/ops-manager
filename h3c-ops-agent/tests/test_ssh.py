#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSH 交互层单测：用假 channel 模拟设备回显，验证协议细节。

重点覆盖三个容易出事的点：
    1. ---- More ---- 分页自动翻页
    2. save force 的 [Y/N] / 文件名确认
    3. 提示符不能被 [flash:/startup.cfg]、[Y/N] 这类文本误判
"""
import re
import unittest

from h3c_ops.ssh import (
    CommandError,
    H3CSession,
    find_error,
    strip_ansi,
)


class FakeChan:
    """最小可用的 paramiko Channel 替身。"""

    def __init__(self):
        self.outbox = ""
        self.sent = []
        self.handlers = {}
        self.closed = False

    def settimeout(self, _timeout):
        pass

    def recv_ready(self):
        return bool(self.outbox)

    def recv(self, size):
        data, self.outbox = self.outbox[:size], self.outbox[size:]
        return data.encode("utf-8")

    def send(self, data):
        self.sent.append(data)
        command = data.strip()
        for key, response in self.handlers.items():
            if command == key:
                self.outbox += response() if callable(response) else response
                break
        return len(data)

    def close(self):
        self.closed = True


def make_session(hostname="SW-Core-01"):
    session = H3CSession(ip="10.0.0.1", username="u", password="p", command_timeout=5, save_timeout=10)
    session.chan = FakeChan()
    session.hostname = hostname
    session._prompt = f"<{hostname}>"
    session._build_prompt_re(hostname)
    return session


class SendTest(unittest.TestCase):
    def test_echo_and_prompt_stripped(self):
        session = make_session()
        session.chan.handlers["display clock"] = (
            "display clock\r\n12:00:00 UTC Thu 10/29/2026\r\n<SW-Core-01>"
        )
        output = session.send("display clock")
        self.assertEqual(output, "12:00:00 UTC Thu 10/29/2026")

    def test_more_paging_is_answered(self):
        session = make_session()

        def first():
            return "line1\r\n---- More ----"

        def rest():
            return "line2\r\n<SW-Core-01>"

        session.chan.handlers["display current-configuration"] = first
        session.chan.handlers[""] = rest  # 翻页只发一个空格，strip 后为空串
        output = session.send("display current-configuration")
        self.assertIn("line1", output)
        self.assertIn("line2", output)
        self.assertIn(" ", session.chan.sent)

    def test_command_error_raises(self):
        session = make_session()
        session.chan.handlers["bogus"] = (
            "% Unrecognized command found at '^' position.\r\n<SW-Core-01>"
        )
        with self.assertRaises(CommandError):
            session.send("bogus", check=True)

    def test_send_safe_returns_error_instead_of_raising(self):
        session = make_session()
        session.chan.handlers["bogus"] = (
            "% Wrong parameter found at '^' position.\r\n<SW-Core-01>"
        )
        output, error = session.send_safe("bogus")
        self.assertTrue(error)
        self.assertIn("Wrong parameter", error)

    def test_already_exists_is_not_an_error(self):
        self.assertIsNone(find_error("% The specified ACL already exists."))
        self.assertIsNone(find_error("Info: The community already exists."))
        self.assertTrue(find_error("% Unrecognized command found"))


class SaveTest(unittest.TestCase):
    def test_save_force_success(self):
        session = make_session()
        session.chan.handlers["save force"] = (
            "Saving configuration flash:/startup.cfg. Please wait...\r\n"
            "Configuration is saved to device successfully.\r\n<SW-Core-01>"
        )
        result = session.save()
        self.assertTrue(result.ok)
        self.assertTrue(result.confirmed)

    def test_y_n_prompt_answered_once(self):
        session = make_session()
        session.chan.handlers["save force"] = (
            "The current configuration will be saved. Continue? [Y/N]:"
        )
        session.chan.handlers["Y"] = (
            "Now saving current configuration to the device.\r\n"
            "Configuration is saved to device successfully.\r\n<SW-Core-01>"
        )
        result = session.save()
        self.assertTrue(result.ok, result.detail)
        self.assertEqual([s for s in session.chan.sent if s.strip() == "Y"], ["Y\n"])

    def test_filename_prompt_accepts_default(self):
        session = make_session()
        session.chan.handlers["save force"] = (
            "Please input the file name(*.cfg)[flash:/startup.cfg]:"
        )
        session.chan.handlers[""] = (
            "Configuration is saved to device successfully.\r\n<SW-Core-01>"
        )
        result = session.save()
        self.assertTrue(result.ok, result.detail)
        # 关键：不能因为 [flash:/startup.cfg] 被当成提示符提前结束
        self.assertNotIn("Y\n", session.chan.sent)

    def test_save_failure_reported(self):
        session = make_session()
        session.chan.handlers["save force"] = (
            "Failed to save the configuration.\r\n<SW-Core-01>"
        )
        result = session.save()
        self.assertFalse(result.ok)
        self.assertIn("失败", result.detail)


class PromptDetectionTest(unittest.TestCase):
    def test_dashed_hostname_is_accepted(self):
        session = H3CSession(ip="10.0.0.1", username="u", password="p")
        session.chan = FakeChan()
        session._detect_hostname("<SW-Core-01>")
        self.assertEqual(session.hostname, "SW-Core-01")
        self.assertTrue(session.prompt_re.search("<SW-Core-01>"))

    def test_hostname_from_banner_with_prefix(self):
        session = H3CSession(ip="10.0.0.1", username="u", password="p")
        session.chan = FakeChan()
        session._detect_hostname(
            "\r\n* Copyright (c) 2004-2021 New H3C Technologies Co., Ltd.\r\n<Access_SW_2F>"
        )
        self.assertEqual(session.hostname, "Access_SW_2F")

    def test_system_view_prompt_returns_to_user_view(self):
        session = H3CSession(ip="10.0.0.1", username="u", password="p")
        session.chan = FakeChan()
        session.chan.handlers["return"] = "<SW1>"
        session._detect_hostname("[SW1]")
        self.assertEqual(session.hostname, "SW1")
        self.assertIn("return\n", session.chan.sent)

    def test_invalid_prompt_raises(self):
        from h3c_ops.ssh import PromptError

        session = H3CSession(ip="10.0.0.1", username="u", password="p")
        session.chan = FakeChan()
        with self.assertRaises(PromptError):
            session._detect_hostname("<bad host name!>")


class ConfigModeTest(unittest.TestCase):
    def test_config_enters_and_leaves(self):
        session = make_session()
        session.chan.handlers["system-view"] = "[SW-Core-01]"
        session.chan.handlers["snmp-agent"] = "[SW-Core-01]"
        session.chan.handlers["return"] = "<SW-Core-01>"
        results = session.config(["snmp-agent"])
        self.assertEqual(results[0][2], None)
        self.assertIn("system-view\n", session.chan.sent)
        self.assertIn("return\n", session.chan.sent)

    def test_config_error_stops_and_exits(self):
        session = make_session()
        session.chan.handlers["system-view"] = "[SW-Core-01]"
        session.chan.handlers["bad-cmd"] = (
            "% Unrecognized command found at '^' position.\r\n[SW-Core-01]"
        )
        session.chan.handlers["return"] = "<SW-Core-01>"
        with self.assertRaises(CommandError):
            session.config(["bad-cmd", "never-sent"])
        self.assertIn("return\n", session.chan.sent)
        self.assertNotIn("never-sent\n", session.chan.sent)


class ElevateTest(unittest.TestCase):
    """super 提权是"问密码"的交互，不走标准命令回显，必须单独验证。"""

    def test_correct_secret_elevates(self):
        session = make_session()
        session.secret = "S3cret!"
        session.chan.handlers["super 3"] = "Password:"
        session.chan.handlers["S3cret!"] = (
            "Now user privilege is 3 level. Press Ctrl+C to abort.\r\n<SW-Core-01>"
        )
        ok, note = session.elevate()
        self.assertTrue(ok, note)
        self.assertIn("3 级", note)
        self.assertIn("S3cret!\n", session.chan.sent)

    def test_wrong_secret_reports_failure(self):
        session = make_session()
        session.secret = "WrongOne"
        session.chan.handlers["super 3"] = "Password:"
        session.chan.handlers["WrongOne"] = (
            "Error: Password is not correct.\r\n<SW-Core-01>"
        )
        ok, note = session.elevate()
        self.assertFalse(ok)
        self.assertIn("提权失败", note)

    def test_already_privileged_is_not_a_failure(self):
        session = make_session()
        session.secret = "S3cret!"
        session.chan.handlers["super 3"] = (
            "Error: The user privilege level is 3, no need to elevate.\r\n<SW-Core-01>"
        )
        ok, note = session.elevate()
        self.assertTrue(ok, note)
        self.assertIn("无需提权", note)

    def test_no_secret_returns_immediately(self):
        session = make_session()
        ok, note = session.elevate()
        self.assertTrue(ok)
        self.assertEqual(session.chan.sent, [])

    def test_missing_password_prompt_reports_reason(self):
        session = make_session()
        session.secret = "S3cret!"
        session.chan.handlers["super 3"] = (
            "Error: The user does not have the privilege to execute the command.\r\n<SW-Core-01>"
        )
        ok, note = session.elevate()
        self.assertFalse(ok)
        self.assertIn("未出现", note)


class StripAnsiTest(unittest.TestCase):
    def test_removes_escape_sequences(self):
        self.assertEqual(strip_ansi("\x1b[1mUP\x1b[0m"), "UP")


if __name__ == "__main__":
    unittest.main()
