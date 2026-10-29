#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用假会话跑完整巡检 / 团体名链路，验证模块间接线（不连真实设备）。"""
import unittest

from h3c_ops.inspect import CMD_CPU, CMD_ENVIRONMENT, CMD_FAN, CMD_INTERFACE_BRIEF, CMD_MANUINFO
from h3c_ops.inspect import CMD_MEMORY, CMD_POWER, CMD_SNMP_CONF, CMD_VERSION, collect
from h3c_ops.snmp import STATUS_DRY, STATUS_OK, apply
from h3c_ops.ssh import SaveResult

OUTPUTS = {
    CMD_VERSION: """H3C Comware Software, Version 7.1.070, Release 3506P10
H3C S5560X-30C-EI uptime is 40 weeks, 2 days, 3 hours, 5 minutes
""",
    CMD_MANUINFO: """Slot 1:
  DEVICE_NAME          : S5560X-30C-EI
  DEVICE_SERIAL_NUMBER : 219801A1XYZ1234567
  MAC_ADDRESS          : 88E0-1234-5678
  MANUFACTURING_DATE   : 2022-03-11
  VENDOR_NAME          : H3C
""",
    CMD_CPU: "Slot 1 CPU usage:\n 5% in last 5 seconds\n 12% in last 1 minute\n 88% in last 5 minutes\n",
    CMD_MEMORY: ("Memory statistics are measured in KB:\nSlot 1:\n"
                 "        Total      Used      Free\nMem:    1048576    786432    262144\n"),
    CMD_ENVIRONMENT: ("System temperature information (degree centigrade):\n"
                      "Sensor  Temperature  Lower  Upper\nhotspot-1  48   0  98\n"),
    CMD_POWER: "Power ID  Status\n1  Normal\n2  Normal\n",
    CMD_FAN: "Fan  State\n1  Normal\n2  Normal\n",
    CMD_INTERFACE_BRIEF: ("Interface  Link  Speed  Duplex Type PVID\n"
                          "GE1/0/1  UP   1G(a)  F(a)   A  1\n"
                          "GE1/0/2  DOWN auto   A      A  1\n"),
    CMD_SNMP_CONF: "",
}


class FakeSession:
    hostname = "SW-Test-01"
    ip = "10.12.20.11"
    command_timeout = 30

    def __init__(self, outputs=None):
        self.outputs = dict(outputs or OUTPUTS)
        self.config_calls = []
        self.saved = 0

    def send_safe(self, command, timeout=None):
        if command in self.outputs:
            return self.outputs[command], None
        return "", f"不支持的测试命令: {command}"

    def sum(self):
        return sum(1 for _ in self.config_calls)

    def config(self, commands, stop_on_error=True):
        self.config_calls.append(list(commands))
        # 模拟设备写入后回显的配置
        self.outputs[CMD_SNMP_CONF] = (
            "snmp-agent\n"
            "snmp-agent sys-info version v2c\n"
            "snmp-agent community read simple OpsRead@2026 acl 2001\n"
            "snmp-agent trap enable\n"
            "snmp-agent target-host trap address udp-domain 10.12.10.50 udp-port 162 "
            "params securityname OpsRead@2026 v2c\n"
        )
        return [(c, "", None) for c in commands]

    def save(self):
        self.saved += 1
        return SaveResult(True, True, "配置已保存")


class CollectTest(unittest.TestCase):
    def test_collect_full_inspection(self):
        insp = collect(FakeSession(), thresholds={
            "cpu_percent": 80, "memory_percent": 85, "temperature": 60, "down_port_count": 0,
        })
        self.assertEqual(insp.hostname, "SW-Test-01")
        self.assertEqual(insp.model, "S5560X-30C-EI")
        self.assertEqual(insp.serial, "219801A1XYZ1234567")
        self.assertEqual(insp.cpu, 88)
        self.assertEqual(insp.mem_percent, 75.0)
        self.assertEqual(insp.max_temp, 48)
        self.assertEqual(insp.fan_bad, [])
        self.assertEqual(insp.power_bad, [])
        self.assertEqual(insp.if_up, 1)
        self.assertEqual(insp.if_total, 2)
        self.assertEqual(insp.down_ports, ["GE1/0/2"])
        self.assertIn("CPU", {i.item for i in insp.issues})
        self.assertEqual(insp.level, "关注")  # CPU 88% 警告 + SNMP 未配置 + 端口 down
        self.assertLess(insp.score, 90)

    def test_partial_command_failure_does_not_abort(self):
        outputs = dict(OUTPUTS)
        outputs.pop(CMD_CPU)
        insp = collect(FakeSession(outputs), thresholds={"cpu_percent": 80})
        self.assertIsNone(insp.cpu)
        self.assertIn(CMD_CPU, insp.failed)
        self.assertEqual(insp.model, "S5560X-30C-EI")


class SnmpApplyTest(unittest.TestCase):
    cfg = {
        "read_community": "OpsRead@2026",
        "write_community": "",
        "acl_number": 2001,
        "acl_sources": ["10.12.10.50"],
        "contact": "netops@example.com",
        "location": "DC-A",
        "disable_complexity_check": True,
        "enable_trap": True,
        "trap_target": "10.12.10.50",
        "trap_port": 162,
        "save_after_apply": True,
    }

    def test_dry_run_writes_nothing(self):
        session = FakeSession()
        result = apply(session, self.cfg, dry_run=True)
        self.assertEqual(result.status, STATUS_DRY)
        self.assertEqual(session.config_calls, [])
        self.assertEqual(session.saved, 0)
        self.assertIn("snmp-agent community read simple OpsRead@2026 acl 2001", result.commands)

    def test_apply_and_verify(self):
        session = FakeSession()
        result = apply(session, dict(self.cfg, acl_number=0, acl_sources=[]), dry_run=False)
        self.assertEqual(result.status, STATUS_OK, result.detail)
        self.assertTrue(result.verified)
        self.assertEqual(session.saved, 1)
        self.assertEqual(len(session.config_calls), 1)

    def test_idempotent_when_already_compliant(self):
        outputs = dict(OUTPUTS)
        outputs[CMD_SNMP_CONF] = (
            "snmp-agent\nsnmp-agent sys-info version v2c\n"
            "snmp-agent community read simple OpsRead@2026 acl 2001\n"
            "snmp-agent trap enable\n"
            "snmp-agent target-host trap address udp-domain 10.12.10.50 udp-port 162 "
            "params securityname OpsRead@2026 v2c\n"
        )
        outputs["display acl 2001"] = (
            "Basic ACL 2001, 1 rule\nACL's step is 5\n"
            " rule 5 permit source 10.12.10.50 0\n"
        )
        session = FakeSession(outputs)
        result = apply(session, self.cfg, dry_run=False)
        self.assertEqual(result.status, "无变化")
        self.assertEqual(session.config_calls, [])
        self.assertEqual(session.saved, 0)

    def test_rejects_short_community(self):
        result = apply(FakeSession(), dict(self.cfg, read_community="H3C"), dry_run=False)
        self.assertEqual(result.status, "失败")
        self.assertIn("8 位", result.detail)


if __name__ == "__main__":
    unittest.main()
