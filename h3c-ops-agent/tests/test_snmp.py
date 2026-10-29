#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SNMP 标准团体名相关纯函数单测。"""
import unittest

from h3c_ops.snmp import (
    build_acl_commands,
    build_commands,
    is_compliant,
    parse_acl,
    parse_config_state,
    validate_community,
)

SAMPLE_CONF = """
#
snmp-agent
snmp-agent sys-info version v2c
snmp-agent sys-info contact netops@example.com
snmp-agent sys-info location DC-A
snmp-agent community complexity-check disable
snmp-agent community read simple OpsRead@2026 acl 2001
snmp-agent trap enable
snmp-agent target-host trap address udp-domain 10.12.10.50 udp-port 162 params securityname OpsRead@2026 v2c
#
"""

CIPHER_CONF = """
snmp-agent
snmp-agent sys-info version v2c
snmp-agent community read cipher $c$3$AbCdEf123456
"""

ACL_OUTPUT = """Basic ACL 2001, 2 rules
ACL's step is 5
 rule 5 permit source 10.12.10.50 0
 rule 10 permit source 10.12.10.51 0
"""


class ParseConfigStateTest(unittest.TestCase):
    def test_full_state(self):
        state = parse_config_state(SAMPLE_CONF)
        self.assertTrue(state["has_snmp"])
        self.assertTrue(state["v2c"])
        self.assertEqual(state["read_communities"], ["OpsRead@2026"])
        self.assertEqual(state["community_acl"]["OpsRead@2026"], 2001)
        self.assertEqual(state["trap_targets"], ["10.12.10.50"])
        self.assertTrue(state["trap_enabled"])
        self.assertEqual(state["contact"], "netops@example.com")
        self.assertEqual(state["location"], "DC-A")

    def test_empty_config(self):
        state = parse_config_state("")
        self.assertFalse(state["has_snmp"])
        self.assertEqual(state["read_communities"], [])

    def test_cipher_community_detected(self):
        state = parse_config_state(CIPHER_CONF)
        self.assertTrue(state["cipher_communities"])
        self.assertNotIn("$c$3$AbCdEf123456", state["read_communities"])


class BuildCommandsTest(unittest.TestCase):
    def base_cfg(self, **overrides):
        cfg = {
            "contact": "netops@example.com",
            "location": "DC-A",
            "disable_complexity_check": True,
            "enable_trap": True,
            "trap_target": "10.12.10.50",
            "trap_port": 162,
            "write_community": "",
        }
        cfg.update(overrides)
        return cfg

    def test_standard_read_only(self):
        commands = build_commands(self.base_cfg(), "OpsRead@2026", acl_number=2001)
        joined = "\n".join(commands)
        self.assertIn("snmp-agent sys-info version v2c", joined)
        self.assertIn("snmp-agent community read simple OpsRead@2026 acl 2001", joined)
        self.assertIn("snmp-agent trap enable", joined)
        self.assertIn("snmp-agent target-host trap address udp-domain 10.12.10.50", joined)
        self.assertFalse(any("community write" in c for c in commands))

    def test_no_acl_no_trap(self):
        commands = build_commands(
            self.base_cfg(enable_trap=False), "OpsRead@2026", acl_number=0
        )
        joined = "\n".join(commands)
        self.assertIn("snmp-agent community read simple OpsRead@2026", joined)
        self.assertNotIn("acl", joined)
        self.assertNotIn("target-host", joined)

    def test_optional_write_community(self):
        commands = build_commands(self.base_cfg(write_community="OpsWrite@2026"), "OpsRead@2026", 2001)
        self.assertIn("snmp-agent community write simple OpsWrite@2026 acl 2001", commands)


class AclTest(unittest.TestCase):
    def test_parse_acl(self):
        exists, rules = parse_acl(ACL_OUTPUT)
        self.assertTrue(exists)
        self.assertEqual(rules[5], "permit source 10.12.10.50 0")
        self.assertEqual(rules[10], "permit source 10.12.10.51 0")

    def test_parse_missing_acl(self):
        exists, rules = parse_acl("% ACL 2001 does not exist.")
        self.assertFalse(exists)
        self.assertEqual(rules, {})

    def test_append_only_missing_source(self):
        _, rules = parse_acl(ACL_OUTPUT)
        commands = build_acl_commands(2001, ["10.12.10.50", "10.12.10.52"], rules)
        self.assertEqual(commands, ["acl basic 2001", "rule 20 permit source 10.12.10.52 0", "quit"])

    def test_nothing_to_do(self):
        _, rules = parse_acl(ACL_OUTPUT)
        self.assertEqual(build_acl_commands(2001, ["10.12.10.50"], rules), [])

    def test_create_from_scratch(self):
        commands = build_acl_commands(2001, ["10.12.10.50", "10.12.10.51"], {})
        self.assertEqual(commands[0], "acl basic 2001")
        self.assertIn("rule 5 permit source 10.12.10.50 0", commands)
        self.assertIn("rule 15 permit source 10.12.10.51 0", commands)


class ComplianceTest(unittest.TestCase):
    def cfg(self):
        return {"enable_trap": True, "trap_target": "10.12.10.50"}

    def test_compliant(self):
        state = parse_config_state(SAMPLE_CONF)
        self.assertTrue(is_compliant(state, "OpsRead@2026", 2001, self.cfg()))

    def test_wrong_community(self):
        state = parse_config_state(SAMPLE_CONF)
        self.assertFalse(is_compliant(state, "OtherCommunity", 2001, self.cfg()))

    def test_missing_acl(self):
        state = parse_config_state(SAMPLE_CONF)
        self.assertFalse(is_compliant(state, "OpsRead@2026", 2002, self.cfg()))

    def test_cipher_not_compliant(self):
        state = parse_config_state(CIPHER_CONF)
        self.assertFalse(is_compliant(state, "OpsRead@2026", 0, {"enable_trap": False}))


class ValidateCommunityTest(unittest.TestCase):
    def test_valid(self):
        self.assertIsNone(validate_community("OpsRead@2026"))

    def test_too_short(self):
        self.assertIn("8 位", validate_community("H3C"))

    def test_space(self):
        self.assertIn("空格", validate_community("Ops Read 2026"))

    def test_empty(self):
        self.assertIsNotNone(validate_community(""))


if __name__ == "__main__":
    unittest.main()
