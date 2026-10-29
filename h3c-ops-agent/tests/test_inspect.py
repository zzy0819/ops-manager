#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""巡检解析器单测（样本取自真实 Comware V7 回显）。"""
import unittest

from h3c_ops.inspect import (
    Inspection,
    Issue,
    evaluate,
    parse_cpu,
    parse_environment,
    parse_fan,
    parse_interfaces,
    parse_manuinfo,
    parse_memory,
    parse_optical,
    parse_power,
    parse_uptime_days,
    parse_version,
)

VERSION = """H3C Comware Software, Version 7.1.070, Release 3506P10
Copyright (c) 2004-2021 New H3C Technologies Co., Ltd. All rights reserved.
H3C S5130S-28P-EI uptime is 123 weeks, 4 days, 5 hours, 33 minutes
Last reboot reason : User reboot

Boot image: flash:/s5130s_ei-cmw710-boot-r3506p10.bin
"""

CPU = """Slot 1 CPU usage:
       1% in last 5 seconds
       2% in last 1 minute
       3% in last 5 minutes
"""

CPU_V5 = "The CPU usage of the MPU is 17%."

MEMORY = """Memory statistics are measured in KB:
Slot 1:
        Total      Used      Free    Shared  Buffers   Cached
Mem:    524288     262144    262144  0       1024      32768
"""

MEMORY_V5 = """System Total Memory(bytes): 1073741824
Total Used Memory(bytes): 268435456
Used Rate: 25%
"""

ENVIRONMENT = """System temperature information (degree centigrade):
--------------------------------------------------------------------------
Sensor  Temperature    Lower  Upper
--------------------------------------------------------------------------
inlet-1     28            0      50
hotspot-1   45            0      98
"""

POWER = """Power ID    Status
1           Normal
2           Fault
"""

FAN = """Fan  State
1    Normal
2    Absent
"""

INTERFACES = """Brief information on interfaces in route mode:
Link: ADM - administratively down; Stby - standby
Protocol: (s) - spoofing
Interface            Link Protocol Primary IP      Description
Vlan1                DOWN DOWN   --
Vlan10               UP   UP     10.12.20.1

Brief information on interfaces in bridge mode:
Link: ADM - administratively down; Stby - standby
Speed: (a) - auto
Duplex: (a)/A - auto; H - half; F - full
Type: A - access; T - trunk; H - hybrid
Interface            Link Speed   Duplex Type PVID Description
GE1/0/1              UP   1G(a)   F(a)   A    1
GE1/0/2              DOWN auto    A      A    1
GE1/0/3              ADM  auto    A      A    1
XGE1/0/49            UP   10G(a)  F(a)   A    1
"""

MANUINFO = """Slot 1:
  DEVICE_NAME          : S5130S-28P-EI
  DEVICE_SERIAL_NUMBER : 219801A2MMP21A000123
  MAC_ADDRESS          : 0011-2233-4455
  MANUFACTURING_DATE   : 2021-05-20
  VENDOR_NAME          : H3C
"""

OPTICAL = """GE1/0/49
  Temp(C):        35
  Voltage(V):     3.29
  RX power(dBm):  -3.21
  TX power(dBm):  -2.85
GE1/0/50
  RX power(dBm):  -25.40
  TX power(dBm):  -2.90
"""


class VersionParserTest(unittest.TestCase):
    def test_comware7(self):
        info = parse_version(VERSION)
        self.assertEqual(info["model"], "S5130S-28P-EI")
        self.assertEqual(info["comware"], "7.1.070")
        self.assertEqual(info["release"], "3506P10")
        self.assertAlmostEqual(info["uptime_days"], 865.23, places=2)

    def test_uptime_variants(self):
        self.assertAlmostEqual(parse_uptime_days("0 weeks, 0 days, 1 hours, 30 minutes"), 0.06, places=2)
        self.assertAlmostEqual(parse_uptime_days("2 days, 3 hours"), 2.125, places=2)
        self.assertIsNone(parse_uptime_days("unknown"))


class CpuMemoryTest(unittest.TestCase):
    def test_cpu_5min_preferred(self):
        self.assertEqual(parse_cpu(CPU), 3)

    def test_cpu_v5(self):
        self.assertEqual(parse_cpu(CPU_V5), 17)

    def test_cpu_multi_slot_takes_max(self):
        text = ("Slot 1 CPU usage:\n 5% in last 5 minutes\n"
                "Slot 2 CPU usage:\n 42% in last 5 minutes\n")
        self.assertEqual(parse_cpu(text), 42)

    def test_memory_v7(self):
        info = parse_memory(MEMORY)
        self.assertEqual(info["total_kb"], 524288)
        self.assertEqual(info["used_kb"], 262144)
        self.assertEqual(info["percent"], 50.0)

    def test_memory_v5(self):
        info = parse_memory(MEMORY_V5)
        self.assertEqual(info["percent"], 25.0)

    def test_memory_missing(self):
        self.assertIsNone(parse_memory("")["percent"])


class EnvironmentTest(unittest.TestCase):
    def test_max_temperature(self):
        info = parse_environment(ENVIRONMENT)
        self.assertEqual(info["max_temp"], 45)
        self.assertEqual(info["sensor"], "hotspot-1")

    def test_single_line_form(self):
        info = parse_environment("System Temperature : 38 degrees centigrade")
        self.assertEqual(info["max_temp"], 38)

    def test_power_and_fan(self):
        total, bad = parse_power(POWER)
        self.assertEqual(total, 2)
        self.assertEqual(bad, ["Power2(Fault)"])

        total, bad = parse_fan(FAN)
        self.assertEqual(total, 2)
        self.assertEqual(bad, [])

    def test_unsupported_command(self):
        self.assertEqual(parse_power("% Unrecognized command found at '^' position."), (0, []))
        self.assertEqual(parse_fan(""), (0, []))


class InterfaceTest(unittest.TestCase):
    def test_counts_and_dedup(self):
        stats = parse_interfaces(INTERFACES)
        self.assertEqual(stats["total"], 6)
        self.assertEqual(stats["up"], 3)
        self.assertEqual(stats["down"], 2)
        self.assertEqual(stats["admin_down"], 1)
        self.assertEqual(stats["down_ports"], ["GE1/0/2"])  # Vlan1 不算物理口

    def test_empty(self):
        self.assertEqual(parse_interfaces("")["total"], 0)


class ManuinfoOpticalTest(unittest.TestCase):
    def test_manuinfo(self):
        info = parse_manuinfo(MANUINFO)
        self.assertEqual(info["serial"], "219801A2MMP21A000123")
        self.assertEqual(info["model"], "S5130S-28P-EI")
        self.assertEqual(info["vendor"], "H3C")

    def test_optical(self):
        self.assertEqual(parse_optical(OPTICAL), ["GE1/0/50(-25.40dBm)"])


class EvaluateTest(unittest.TestCase):
    def thresholds(self):
        return {"cpu_percent": 80, "memory_percent": 85, "temperature": 60, "down_port_count": 0}

    def test_healthy_device(self):
        insp = Inspection(hostname="SW1", cpu=10, mem_percent=40, max_temp=35,
                          snmp={"has_snmp": True, "v2c": True})
        evaluate(insp, self.thresholds())
        self.assertEqual(insp.level, "正常")
        self.assertEqual(insp.score, 100)

    def test_critical_device(self):
        insp = Inspection(hostname="SW2", cpu=95, mem_percent=92, max_temp=75,
                          fan_bad=["Fan2(Fault)"], down_ports=["GE1/0/2", "GE1/0/3"],
                          snmp={"has_snmp": False})
        evaluate(insp, self.thresholds())
        self.assertEqual(insp.level, "严重")
        self.assertLess(insp.score, 60)
        items = {i.item for i in insp.issues}
        self.assertTrue({"CPU", "内存", "温度", "风扇", "端口", "SNMP"} <= items)

    def test_score_floor(self):
        insp = Inspection(hostname="SW3", cpu=99, mem_percent=99, max_temp=99,
                          fan_bad=["x"], power_bad=["y"], down_ports=["a", "b"],
                          snmp={"has_snmp": False}, uptime_days=0.1)
        evaluate(insp, self.thresholds())
        self.assertEqual(insp.score, 0)

    def test_missing_metrics_are_info_only(self):
        insp = Inspection(hostname="SW4", snmp={"has_snmp": True, "v2c": True})
        evaluate(insp, self.thresholds())
        self.assertTrue(all(i.level == "提示" for i in insp.issues))
        self.assertGreaterEqual(insp.score, 90)


if __name__ == "__main__":
    unittest.main()
