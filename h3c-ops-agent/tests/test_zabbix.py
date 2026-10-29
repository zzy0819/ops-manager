#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zabbix 接入计划单测（不访问网络）。"""
import unittest

from h3c_ops.zabbix import STATUS_CONFLICT, STATUS_OK, STATUS_SKIP, HostSpec, plan_host

SPEC = HostSpec(
    name="SW-Core-01",
    ip="10.12.20.1",
    community="OpsRead@2026",
    group_name="网络设备/华三交换机",
    template_name="H3C Comware by SNMP",
    port=161,
)

EXISTING = {
    "hostid": "10101",
    "host": "SW-Core-01",
    "name": "SW-Core-01",
    "status": "0",
    "groups": [{"groupid": "2", "name": "网络设备/华三交换机"}],
    "parentTemplates": [{"templateid": "10001", "name": "H3C Comware by SNMP"}],
    "interfaces": [{
        "interfaceid": "55", "type": "2", "main": "1",
        "ip": "10.12.20.1", "port": "161",
        "details": {"version": "2", "community": "{$SNMP_COMMUNITY}"},
    }],
    "macros": [{"macro": "{$SNMP_COMMUNITY}", "value": "OpsRead@2026"}],
}


class CreatePlanTest(unittest.TestCase):
    def test_new_host_payload(self):
        plan = plan_host(None, SPEC, "2", "10001")
        self.assertEqual(plan.action, STATUS_OK)
        self.assertEqual(plan.method, "host.create")
        params = plan.params
        self.assertEqual(params["host"], "SW-Core-01")
        self.assertEqual(params["status"], 0)
        self.assertEqual(params["groups"], [{"groupid": "2"}])
        self.assertEqual(params["templates"], [{"templateid": "10001"}])

        interface = params["interfaces"][0]
        self.assertEqual(interface["type"], 2)
        self.assertEqual(interface["ip"], "10.12.20.1")
        self.assertEqual(interface["port"], "161")
        self.assertEqual(interface["details"]["version"], 2)
        self.assertEqual(interface["details"]["community"], "{$SNMP_COMMUNITY}")

        self.assertEqual(params["macros"], [{"macro": "{$SNMP_COMMUNITY}", "value": "OpsRead@2026"}])
        self.assertEqual(params["tags"][0]["tag"], "managed_by")

    def test_proxy_attached(self):
        plan = plan_host(None, SPEC, "2", "10001", proxy_id="7")
        self.assertEqual(plan.params["proxyid"], "7")


class IdempotentTest(unittest.TestCase):
    def test_compliant_host_is_skipped(self):
        plan = plan_host(EXISTING, SPEC, "2", "10001")
        self.assertEqual(plan.action, STATUS_SKIP)
        self.assertEqual(plan.changes, [])

    def test_missing_template_is_added_without_losing_existing(self):
        existing = dict(EXISTING)
        existing["parentTemplates"] = [{"templateid": "999", "name": "ICMP Ping"}]
        plan = plan_host(existing, SPEC, "2", "10001")
        self.assertEqual(plan.method, "host.update")
        template_ids = {t["templateid"] for t in plan.params["templates"]}
        self.assertEqual(template_ids, {"999", "10001"})

    def test_missing_group_keeps_existing_groups(self):
        existing = dict(EXISTING)
        existing["groups"] = [{"groupid": "2", "name": "网络设备"}, {"groupid": "9", "name": "其他"}]
        plan = plan_host(existing, SPEC, "3", "10001")
        group_ids = {g["groupid"] for g in plan.params["groups"]}
        self.assertEqual(group_ids, {"2", "9", "3"})

    def test_macro_change_keeps_other_macros(self):
        existing = dict(EXISTING)
        existing["macros"] = [
            {"macro": "{$SNMP_COMMUNITY}", "value": "Old@2025"},
            {"macro": "{$ALERT_LEVEL}", "value": "3"},
        ]
        plan = plan_host(existing, SPEC, "2", "10001")
        macros = {m["macro"]: m["value"] for m in plan.params["macros"]}
        self.assertEqual(macros["{$SNMP_COMMUNITY}"], "OpsRead@2026")
        self.assertEqual(macros["{$ALERT_LEVEL}"], "3")

    def test_disabled_host_is_enabled(self):
        existing = dict(EXISTING)
        existing["status"] = "1"
        plan = plan_host(existing, SPEC, "2", "10001")
        self.assertEqual(plan.params["status"], 0)


class ConflictTest(unittest.TestCase):
    def test_ip_mismatch_is_conflict_by_default(self):
        existing = dict(EXISTING)
        existing["interfaces"] = [{
            "interfaceid": "55", "type": "2", "main": "1", "ip": "10.12.20.99", "port": "161",
            "details": {"version": "2"},
        }]
        plan = plan_host(existing, SPEC, "2", "10001")
        self.assertEqual(plan.action, STATUS_CONFLICT)

    def test_ip_mismatch_overwritten_when_allowed(self):
        existing = dict(EXISTING)
        existing["interfaces"] = [{
            "interfaceid": "55", "type": "2", "main": "1", "ip": "10.12.20.99", "port": "161",
            "details": {"version": "2"},
        }]
        spec = HostSpec(**{**SPEC.__dict__, "overwrite_interface": True})
        plan = plan_host(existing, spec, "2", "10001")
        self.assertEqual(plan.method, "host.update")
        self.assertEqual(plan.extra_calls[0][0], "hostinterface.update")
        self.assertEqual(plan.extra_calls[0][1]["ip"], "10.12.20.1")

    def test_missing_snmp_interface_is_created(self):
        existing = dict(EXISTING)
        existing["interfaces"] = [{
            "interfaceid": "77", "type": "1", "main": "1", "ip": "10.12.20.1", "port": "10050",
            "details": {},
        }]
        plan = plan_host(existing, SPEC, "2", "10001")
        self.assertEqual(plan.extra_calls[0][0], "hostinterface.create")
        self.assertEqual(plan.extra_calls[0][1]["type"], 2)


if __name__ == "__main__":
    unittest.main()
