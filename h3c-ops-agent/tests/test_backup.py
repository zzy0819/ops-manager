#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置备份单测：落盘、差异对比、保留策略。"""
import tempfile
import unittest
from pathlib import Path

from h3c_ops.backup import (
    STATUS_CHANGED,
    STATUS_OK,
    backup,
    diff_configs,
    list_snapshots,
    normalize_config,
    prune,
    resolve_dir,
    safe_name,
)
from h3c_ops.config import DEFAULTS, Config, _merge
from h3c_ops.ssh import SaveResult

CONFIG_A = """#
 sysname SW-Core-01
#
vlan 10
#
interface Vlan-interface10
 ip address 10.12.20.1 255.255.255.0
#
return
"""

CONFIG_B = """#
 sysname SW-Core-01
#
vlan 10
vlan 20
#
interface Vlan-interface10
 ip address 10.12.20.1 255.255.255.0
#
return
"""


class FakeSession:
    hostname = "SW-Core-01"
    ip = "10.12.20.1"

    def __init__(self, text, save_ok=True):
        self.text = text
        self.save_ok = save_ok
        self.save_calls = 0

    def send_safe(self, command, timeout=None):
        return self.text, None

    def save(self):
        self.save_calls += 1
        return SaveResult(self.save_ok, self.save_ok, "ok" if self.save_ok else "failed")


class NormalizeTest(unittest.TestCase):
    def test_strip_trailing_spaces_and_collapse_blanks(self):
        raw = "line1   \r\n\r\n\r\nline2\t\n\n"
        self.assertEqual(normalize_config(raw), "line1\n\nline2\n")

    def test_empty(self):
        self.assertEqual(normalize_config(""), "")


class DiffTest(unittest.TestCase):
    def test_identical(self):
        result = diff_configs(CONFIG_A, CONFIG_A)
        self.assertFalse(result["changed"])
        self.assertEqual(result["added"], 0)

    def test_added_vlan(self):
        result = diff_configs(CONFIG_A, CONFIG_B)
        self.assertTrue(result["changed"])
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["removed"], 0)
        self.assertTrue(any("+vlan 20" in line for line in result["diff"]))

    def test_format_only_change_is_ignored(self):
        noisy = CONFIG_A.replace("\n", "   \n")
        self.assertFalse(diff_configs(CONFIG_A, noisy)["changed"])


class SafeNameTest(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(safe_name("SW-Core/01"), "SW-Core_01")
        self.assertEqual(safe_name(""), "unknown")


class BackupFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = _merge(DEFAULTS, {
            "global": {"backup_dir": str(Path(self.tmp.name) / "backups")},
            "backup": {"keep": 3, "save_before_backup": False},
        })
        self.cfg = Config(data, Path(self.tmp.name) / "config.json")

    def test_first_and_second_backup(self):
        first = backup(FakeSession(CONFIG_A), self.cfg)
        self.assertEqual(first.status, STATUS_OK)
        self.assertIn("首次备份", first.detail)
        self.assertTrue(Path(first.path).exists())

        second = backup(FakeSession(CONFIG_A), self.cfg)
        self.assertEqual(second.status, STATUS_OK)
        self.assertIn("一致", second.detail)
        self.assertFalse(second.changed)

    def test_change_produces_diff_file(self):
        backup(FakeSession(CONFIG_A), self.cfg)
        result = backup(FakeSession(CONFIG_B), self.cfg)
        self.assertEqual(result.status, STATUS_CHANGED)
        self.assertEqual(result.added, 1)
        diff_files = list(resolve_dir(self.cfg, "SW-Core-01").glob("*.diff"))
        self.assertEqual(len(diff_files), 1)
        self.assertIn("vlan 20", diff_files[0].read_text(encoding="utf-8"))

    def test_save_before_backup_respects_config(self):
        self.cfg.data["backup"]["save_before_backup"] = True
        session = FakeSession(CONFIG_A)
        backup(session, self.cfg)
        self.assertEqual(session.save_calls, 1)

    def test_save_failure_aborts(self):
        self.cfg.data["backup"]["save_before_backup"] = True
        result = backup(FakeSession(CONFIG_A, save_ok=False), self.cfg)
        self.assertEqual(result.status, "失败")

    def test_empty_output_fails(self):
        result = backup(FakeSession(""), self.cfg)
        self.assertEqual(result.status, "失败")

    def test_retention_keeps_latest_n_and_never_drops_latest(self):
        for _ in range(4):
            backup(FakeSession(CONFIG_A), self.cfg)
        directory = resolve_dir(self.cfg, "SW-Core-01")
        snapshots = [p for p in directory.glob("*.cfg") if p.name != "latest.cfg"]
        self.assertEqual(len(snapshots), 3)  # keep=3
        self.assertTrue((directory / "latest.cfg").exists())
        self.assertEqual(len(list_snapshots(self.cfg, "SW-Core-01")), 3)

    def test_prune_removes_orphan_files(self):
        directory = resolve_dir(self.cfg, "SW-Core-01")
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(5):
            (directory / f"2026010{index}_000000.cfg").write_text("x", encoding="utf-8")
            (directory / f"2026010{index}_000000.diff").write_text("y", encoding="utf-8")
        removed = prune(directory, 2)
        self.assertEqual(len(list(directory.glob("*.cfg"))), 2)
        self.assertEqual(len(list(directory.glob("*.diff"))), 2)
        self.assertEqual(len(removed), 6)


if __name__ == "__main__":
    unittest.main()
