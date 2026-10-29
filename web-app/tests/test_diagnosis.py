"""网络连通性诊断工具箱 - 综合测试套件

测试范围：
1. 服务层单元测试（输入校验、业务逻辑）
2. 路由层集成测试（API 端点、参数校验、错误处理）
3. 安全性测试（命令注入防护）
4. 故障摘要逻辑测试
"""

import json
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.diagnosis_service import (
    _is_valid_host,
    _is_valid_port,
    DiagnosisService,
)
from app import create_app


# ===========================================================================
# 1. 输入校验单元测试
# ===========================================================================

class TestIsValidHost(unittest.TestCase):
    """_is_valid_host 输入校验测试"""

    # --- 合法输入 ---
    def test_valid_ipv4_127(self):
        self.assertTrue(_is_valid_host('127.0.0.1'))

    def test_valid_ipv4_private(self):
        self.assertTrue(_is_valid_host('192.168.1.1'))

    def test_valid_ipv4_10(self):
        self.assertTrue(_is_valid_host('10.0.0.1'))

    def test_valid_domain_simple(self):
        self.assertTrue(_is_valid_host('baidu.com'))

    def test_valid_domain_subdomain(self):
        self.assertTrue(_is_valid_host('sub.domain.example.com'))

    def test_valid_ip_0_0_0_0(self):
        """0.0.0.0 格式合法（各 octet 0-255）"""
        self.assertTrue(_is_valid_host('0.0.0.0'))

    # --- 非法输入 ---
    def test_invalid_ip_octet_over_255(self):
        self.assertFalse(_is_valid_host('10.0.0.999'))

    def test_invalid_ip_256(self):
        self.assertFalse(_is_valid_host('256.1.1.1'))

    def test_empty_string(self):
        self.assertFalse(_is_valid_host(''))

    def test_too_long_host(self):
        self.assertFalse(_is_valid_host('a' * 254))

    # --- 命令注入防护 ---
    def test_injection_semicolon(self):
        self.assertFalse(_is_valid_host('; rm -rf /'))

    def test_injection_pipe(self):
        self.assertFalse(_is_valid_host('| cat /etc/passwd'))

    def test_injection_backtick(self):
        self.assertFalse(_is_valid_host('\x60whoami\x60'))

    def test_injection_dollar_paren(self):
        self.assertFalse(_is_valid_host('$(whoami)'))

    def test_injection_double_ampersand(self):
        self.assertFalse(_is_valid_host('10.0.0.1 && whoami'))

    def test_injection_semicolon_after_ip(self):
        self.assertFalse(_is_valid_host('192.168.1.1;ls'))

    def test_injection_newline(self):
        self.assertFalse(_is_valid_host('127.0.0.1\nwhoami'))

    def test_injection_redirect(self):
        self.assertFalse(_is_valid_host('127.0.0.1 > /tmp/x'))


class TestIsValidPort(unittest.TestCase):
    """_is_valid_port 端口校验测试"""

    def test_valid_port_80(self):
        self.assertTrue(_is_valid_port('80'))

    def test_valid_port_1(self):
        self.assertTrue(_is_valid_port('1'))

    def test_valid_port_65535(self):
        self.assertTrue(_is_valid_port('65535'))

    def test_invalid_port_0(self):
        self.assertFalse(_is_valid_port('0'))

    def test_invalid_port_65536(self):
        self.assertFalse(_is_valid_port('65536'))

    def test_invalid_port_negative(self):
        self.assertFalse(_is_valid_port('-1'))

    def test_invalid_port_non_numeric(self):
        self.assertFalse(_is_valid_port('abc'))

    def test_invalid_port_empty(self):
        self.assertFalse(_is_valid_port(''))

    def test_invalid_port_float(self):
        self.assertFalse(_is_valid_port('3.14'))

    def test_invalid_port_none(self):
        self.assertFalse(_is_valid_port(None))


# ===========================================================================
# 2. DiagnosisService 业务逻辑测试
# ===========================================================================

class TestDiagnosisServiceInjectionRejection(unittest.TestCase):
    """各诊断方法对命令注入的拒绝测试"""

    INJECTION_INPUTS = [
        '; rm -rf /',
        '| cat /etc/passwd',
        '\x60whoami\x60',
        '$(whoami)',
        '10.0.0.1 && whoami',
    ]

    def test_ping_rejects_injection(self):
        for host in self.INJECTION_INPUTS:
            with self.subTest(host=host):
                result = DiagnosisService.ping(host)
                self.assertFalse(result['success'])
                self.assertIn('不合法', result['error'])

    def test_traceroute_rejects_injection(self):
        for host in self.INJECTION_INPUTS:
            with self.subTest(host=host):
                result = DiagnosisService.traceroute(host)
                self.assertFalse(result['success'])

    def test_port_scan_rejects_injection(self):
        for host in self.INJECTION_INPUTS:
            with self.subTest(host=host):
                result = DiagnosisService.port_scan(host, [80])
                self.assertFalse(result['success'])

    def test_dns_resolve_rejects_injection(self):
        for host in self.INJECTION_INPUTS:
            with self.subTest(host=host):
                result = DiagnosisService.dns_resolve(host)
                self.assertFalse(result['success'])

    def test_full_diagnosis_rejects_injection(self):
        for host in self.INJECTION_INPUTS:
            with self.subTest(host=host):
                result = DiagnosisService.full_diagnosis(host)
                self.assertFalse(result['success'])


class TestDiagnosisServicePortScanEdgeCases(unittest.TestCase):
    """端口探测边界测试"""

    def test_empty_ports_list(self):
        result = DiagnosisService.port_scan('127.0.0.1', [])
        self.assertFalse(result['success'])
        self.assertIn('未指定端口', result['error'])

    def test_port_zero_is_invalid(self):
        result = DiagnosisService.port_scan('127.0.0.1', [0])
        self.assertTrue(result['success'])  # overall success
        self.assertEqual(result['ports'][0]['status'], 'invalid')

    def test_port_over_range_is_invalid(self):
        result = DiagnosisService.port_scan('127.0.0.1', [99999])
        self.assertTrue(result['success'])
        self.assertEqual(result['ports'][0]['status'], 'invalid')

    def test_mixed_valid_invalid_ports(self):
        result = DiagnosisService.port_scan('127.0.0.1', [0, 80, 99999])
        self.assertTrue(result['success'])
        self.assertEqual(result['ports'][0]['status'], 'invalid')
        self.assertIn(result['ports'][1]['status'], ['open', 'closed', 'error'])
        self.assertEqual(result['ports'][2]['status'], 'invalid')


class TestDiagnosisServiceSummary(unittest.TestCase):
    """_generate_summary 故障摘要逻辑测试"""

    def _make_summary(self, ping_loss, port_open, dns_ok, hops=None):
        ping_result = {'success': True, 'loss_rate': ping_loss}
        traceroute_result = {'success': True, 'hops': hops or []}
        port_result = {'success': True, 'open_count': port_open}
        dns_result = {'success': dns_ok, 'ips': ['1.2.3.4'] if dns_ok else []}
        return DiagnosisService._generate_summary(
            'x', ping_result, traceroute_result, port_result, dns_result
        )

    def test_dns_fail_returns_dns_layer(self):
        s = self._make_summary(ping_loss=0, port_open=0, dns_ok=False)
        self.assertEqual(s['status'], 'unreachable')
        self.assertEqual(s['fault_layer'], 'dns')

    def test_icmp_filtered(self):
        """Ping 不可达但端口开放 -> ICMP 被过滤"""
        s = self._make_summary(ping_loss=100, port_open=1, dns_ok=True)
        self.assertEqual(s['status'], 'partial')
        self.assertEqual(s['fault_layer'], 'icmp_filtered')

    def test_port_layer_issue(self):
        """Ping 可达但端口不通 -> 端口层问题"""
        s = self._make_summary(ping_loss=0, port_open=0, dns_ok=True)
        self.assertEqual(s['status'], 'partial')
        self.assertEqual(s['fault_layer'], 'port')

    def test_all_reachable(self):
        """全部正常 -> 可达"""
        s = self._make_summary(ping_loss=0, port_open=1, dns_ok=True)
        self.assertEqual(s['status'], 'reachable')
        self.assertEqual(s['fault_layer'], 'none')

    def test_network_unreachable(self):
        """Ping 不可达且端口不通 -> 网络层问题"""
        s = self._make_summary(ping_loss=100, port_open=0, dns_ok=True)
        self.assertEqual(s['status'], 'unreachable')
        self.assertEqual(s['fault_layer'], 'network')

    def test_traceroute_broken(self):
        """Traceroute 最后 3 跳以上连续超时 -> 路由问题"""
        hops = [
            {'hop': 1, 'timeout': False, 'times': [1, 1, 1]},
            {'hop': 2, 'timeout': True, 'times': [None, None, None]},
            {'hop': 3, 'timeout': True, 'times': [None, None, None]},
            {'hop': 4, 'timeout': True, 'times': [None, None, None]},
        ]
        s = self._make_summary(ping_loss=0, port_open=1, dns_ok=True, hops=hops)
        self.assertEqual(s['status'], 'partial')
        self.assertEqual(s['fault_layer'], 'route')


# ===========================================================================
# 3. 路由层集成测试（Flask test client）
# ===========================================================================

class TestDiagnosisRoutes(unittest.TestCase):
    """诊断路由集成测试"""

    @classmethod
    def setUpClass(cls):
        app = create_app()
        app.config['TESTING'] = True
        cls.client = app.test_client()

    # --- 主页面 ---

    def test_diagnosis_page_returns_200(self):
        """诊断主页面返回 200"""
        resp = self.client.get('/diagnosis/')
        self.assertEqual(resp.status_code, 200)

    def test_diagnosis_page_contains_5_tabs(self):
        """诊断页面包含 5 个 Tab 面板"""
        data = resp = self.client.get('/diagnosis/').data.decode('utf-8')
        self.assertIn('ping-panel', data)
        self.assertIn('traceroute-panel', data)
        self.assertIn('port-panel', data)
        self.assertIn('dns-panel', data)
        self.assertIn('full-panel', data)

    # --- Ping API ---

    def test_ping_success(self):
        """Ping 127.0.0.1 返回成功"""
        resp = self.client.post(
            '/diagnosis/ping',
            data=json.dumps({'host': '127.0.0.1', 'count': 2}),
            content_type='application/json',
        )
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertIn('loss_rate', data)
        self.assertIn('avg_latency', data)
        self.assertIn('details', data)

    def test_ping_missing_host(self):
        """Ping 缺少 host 参数返回 400"""
        resp = self.client.post(
            '/diagnosis/ping',
            data=json.dumps({'count': 2}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data['success'])

    def test_ping_invalid_host(self):
        """Ping 非法 host 返回 400"""
        resp = self.client.post(
            '/diagnosis/ping',
            data=json.dumps({'host': '; rm -rf /', 'count': 2}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data['success'])

    # --- Traceroute API ---

    def test_traceroute_missing_host(self):
        """Traceroute 缺少 host 返回 400"""
        resp = self.client.post(
            '/diagnosis/traceroute',
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    # --- Port Scan API ---

    def test_port_scan_missing_ports(self):
        """端口探测缺少 ports 返回 400"""
        resp = self.client.post(
            '/diagnosis/port_scan',
            data=json.dumps({'host': '127.0.0.1'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_port_scan_comma_separated(self):
        """端口探测接受逗号分隔端口字符串"""
        resp = self.client.post(
            '/diagnosis/port_scan',
            data=json.dumps({'host': '127.0.0.1', 'ports': '80,443'}),
            content_type='application/json',
        )
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['total'], 2)

    # --- DNS API ---

    def test_dns_missing_domain(self):
        """DNS 缺少 domain 返回 400"""
        resp = self.client.post(
            '/diagnosis/dns',
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_dns_localhost(self):
        """DNS 解析 localhost 返回成功"""
        resp = self.client.post(
            '/diagnosis/dns',
            data=json.dumps({'domain': 'localhost'}),
            content_type='application/json',
        )
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertIn('127.0.0.1', data['ips'])

    # --- Full Diagnosis API ---

    def test_full_missing_target(self):
        """一键诊断缺少 target 返回 400"""
        resp = self.client.post(
            '/diagnosis/full',
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    # --- HTTP 方法限制 ---

    def test_ping_get_not_allowed(self):
        """Ping 端点不允许 GET 请求"""
        resp = self.client.get('/diagnosis/ping')
        self.assertEqual(resp.status_code, 405)

    def test_traceroute_get_not_allowed(self):
        resp = self.client.get('/diagnosis/traceroute')
        self.assertEqual(resp.status_code, 405)

    def test_port_scan_get_not_allowed(self):
        resp = self.client.get('/diagnosis/port_scan')
        self.assertEqual(resp.status_code, 405)

    def test_dns_get_not_allowed(self):
        resp = self.client.get('/diagnosis/dns')
        self.assertEqual(resp.status_code, 405)

    def test_full_get_not_allowed(self):
        resp = self.client.get('/diagnosis/full')
        self.assertEqual(resp.status_code, 405)


# ===========================================================================
# 4. 代码结构验证
# ===========================================================================

class TestCodeStructure(unittest.TestCase):
    """代码结构与配置验证"""

    def test_diagnosis_bp_registered(self):
        """确认 diagnosis_bp 在 __init__.py 中注册"""
        from app.routes import register_blueprints
        import inspect
        source = inspect.getsource(register_blueprints)
        self.assertIn('diagnosis_bp', source)
        self.assertIn('register_blueprint(diagnosis_bp)', source)

    def test_diagnosis_bp_has_6_routes(self):
        """确认 diagnosis_bp 有 6 个路由（1 页面 + 5 API）"""
        # 获取 app 中注册后的 url_map
        app = create_app()
        diagnosis_routes = [
            rule.rule for rule in app.url_map.iter_rules()
            if rule.rule.startswith('/diagnosis')
        ]
        self.assertIn('/diagnosis/', diagnosis_routes)
        self.assertIn('/diagnosis/ping', diagnosis_routes)
        self.assertIn('/diagnosis/traceroute', diagnosis_routes)
        self.assertIn('/diagnosis/port_scan', diagnosis_routes)
        self.assertIn('/diagnosis/dns', diagnosis_routes)
        self.assertIn('/diagnosis/full', diagnosis_routes)


if __name__ == '__main__':
    unittest.main(verbosity=2)
