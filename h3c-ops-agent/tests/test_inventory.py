#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设备清单与配置加载单测。"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from h3c_ops.config import Config, ConfigError, load_config, require
from h3c_ops.inventory import read_inventory, valid_host, write_template


def make_xlsx(path: Path, rows) -> Path:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_read_valid_rows_and_defaults(self):
        path = make_xlsx(self.root / "devices.xlsx", [
            ["设备名称", "IP", "用户名", "密码", "端口", "分组"],
            ["SW1", "10.12.20.1", "netops", "P@ss1234", 22, "核心"],
            ["SW2", "10.12.21.1", "", "", "", ""],
        ])
        devices, rejected = read_inventory(
            path, default_user="admin", default_password="Default123"
        )
        self.assertEqual(len(devices), 2)
        self.assertEqual(rejected, [])
        self.assertEqual(devices[0].name, "SW1")
        self.assertEqual(devices[0].group, "核心")
        self.assertEqual(devices[1].username, "admin")
        self.assertEqual(devices[1].port, 22)

    def test_rejects_bad_ip_and_duplicates(self):
        path = make_xlsx(self.root / "devices.xlsx", [
            ["IP", "用户名", "密码"],
            ["300.1.1.1", "u", "p"],          # 非法 IP
            ["10.12.20.1", "u", "p"],
            ["10.12.20.1", "u", "p"],          # 重复
            ["10.12.20.2", "", ""],            # 缺凭据
        ])
        devices, rejected = read_inventory(path)
        self.assertEqual(len(devices), 1)
        self.assertEqual(len(rejected), 3)
        self.assertIn("格式不合法", rejected[0].reason)
        self.assertIn("重复", rejected[1].reason)
        self.assertIn("用户名", rejected[2].reason)

    def test_disabled_row_is_flagged(self):
        path = make_xlsx(self.root / "devices.xlsx", [
            ["IP", "用户名", "密码", "启用"],
            ["10.12.20.1", "u", "p", "否"],
        ])
        devices, _ = read_inventory(path)
        self.assertFalse(devices[0].enabled)

    def test_missing_ip_column(self):
        path = make_xlsx(self.root / "devices.xlsx", [["设备名", "用户名"], ["SW1", "u"]])
        with self.assertRaises(ValueError):
            read_inventory(path)

    def test_csv_input(self):
        path = self.root / "devices.csv"
        path.write_text("IP,用户名,密码\n10.12.20.1,u,p\n", encoding="utf-8-sig")
        devices, _ = read_inventory(path)
        self.assertEqual(devices[0].ip, "10.12.20.1")

    def test_json_input(self):
        path = self.root / "devices.json"
        path.write_text(json.dumps({"devices": [
            {"IP": "10.12.20.1", "username": "u", "password": "p"}
        ]}), encoding="utf-8")
        devices, _ = read_inventory(path)
        self.assertEqual(len(devices), 1)

    def test_template_roundtrip(self):
        path = write_template(self.root / "template.xlsx")
        devices, rejected = read_inventory(path, default_user="netops", default_password="P@ss1234")
        self.assertEqual(rejected, [])
        self.assertEqual(len(devices), 2)  # 模板自带两行示例

    def test_valid_host(self):
        self.assertTrue(valid_host("10.12.20.1"))
        self.assertTrue(valid_host("sw-core-01.corp.local"))
        self.assertFalse(valid_host("10.12.20"))
        self.assertFalse(valid_host("300.1.1.1"))


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_defaults_are_merged(self):
        path = self.root / "config.json"
        path.write_text(json.dumps({"zabbix": {"url": "http://zbx/"}}), encoding="utf-8")
        cfg = load_config(path)
        self.assertEqual(cfg.get("zabbix.url"), "http://zbx")   # 末尾斜杠被清理
        self.assertEqual(cfg.get("global.concurrency"), 8)      # 默认值补齐
        self.assertEqual(cfg.get("inspect.thresholds.cpu_percent"), 80)

    def test_env_override_password(self):
        path = self.root / "config.json"
        path.write_text(json.dumps({"credentials": {"username": "u", "password": "x"}}), encoding="utf-8")
        os.environ["H3C_PASSWORD"] = "from-env"
        try:
            cfg = load_config(path)
        finally:
            os.environ.pop("H3C_PASSWORD")
        self.assertEqual(cfg.get("credentials.password"), "from-env")

    def test_missing_file_raises(self):
        with self.assertRaises(ConfigError):
            load_config(self.root / "nope.json")

    def test_bad_json_raises(self):
        path = self.root / "config.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_acl_number_cleared_without_sources(self):
        path = self.root / "config.json"
        path.write_text(json.dumps({"snmp": {"acl_number": 2001, "acl_sources": []}}), encoding="utf-8")
        cfg = load_config(path)
        self.assertEqual(cfg.get("snmp.acl_number"), 0)

    def test_require(self):
        cfg = Config({"snmp": {"read_community": ""}}, None)
        self.assertEqual(require(cfg, "snmp.read_community"), ["snmp.read_community"])


if __name__ == "__main__":
    unittest.main()
