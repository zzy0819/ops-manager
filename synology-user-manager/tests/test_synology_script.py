"""单文件脚本 synology_user_manager.py 的端到端测试。

启动一个本地假 DSM HTTP 服务，不连接真实 NAS。
"""

import contextlib
import io
import json
import os
import sys
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import synology_user_manager as syno


class FakeDsmState:
    users = [
        {
            'name': 'alice',
            'description': '财务部',
            'email': 'alice@example.com',
            'groups': ['users', 'finance'],
            'expired': 'normal',
            'cannot_chg_passwd': False,
            'passwd_never_expire': True,
            'password_last_change': 19789,
            '2fa_status': 'enabled',
        },
        {
            'name': 'admin',
            'description': '管理员',
            'email': 'admin@example.com',
            'groups': ['users', 'administrators'],
            'expired': 'now',
            'cannot_chg_passwd': False,
            'passwd_never_expire': True,
            'password_last_change': 19789,
            '2fa_status': 'disabled',
        },
        {
            'name': 'guest',
            'description': 'Guest',
            'email': '',
            'groups': ['users'],
            'expired': 'now',
            'cannot_chg_passwd': False,
            'passwd_never_expire': True,
            'password_last_change': 0,
            '2fa_status': 'disabled',
        },
    ]
    set_calls = []
    login_attempts = []
    fail_login_code = None
    fail_list_with_2fa = False
    logout_calls = []


class FakeDsmHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _params(self):
        parsed = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        if self.command == 'POST':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length).decode('utf-8')
            query.update(dict(urllib.parse.parse_qsl(body, keep_blank_values=True)))
        return parsed.path, query

    def _send(self, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self):
        path, params = self._params()
        api = params.get('api')

        if path == '/webapi/auth.cgi' and api == 'SYNO.API.Auth':
            if params.get('method') == 'login':
                FakeDsmState.login_attempts.append(params)
                if FakeDsmState.fail_login_code:
                    self._send({'success': False, 'error': {'code': FakeDsmState.fail_login_code}})
                else:
                    self._send({'success': True, 'data': {'sid': 'FAKE-SID'}})
                return
            if params.get('method') == 'logout':
                FakeDsmState.logout_calls.append(params)
                self._send({'success': True, 'data': {}})
                return
            self._send({'success': False, 'error': {'code': 103}})
            return

        if path == '/webapi/entry.cgi' and api == 'SYNO.Core.User':
            method = params.get('method')
            if method == 'list':
                if FakeDsmState.fail_list_with_2fa and '2fa_status' in params.get('additional', ''):
                    self._send({'success': False, 'error': {'code': 101}})
                else:
                    self._send({
                        'success': True,
                        'data': {'users': FakeDsmState.users, 'total': len(FakeDsmState.users)},
                    })
                return
            if method == 'get':
                for user in FakeDsmState.users:
                    if user['name'] == params.get('name'):
                        self._send({'success': True, 'data': {'users': [user]}})
                        return
                self._send({'success': False, 'error': {'code': 102}})
                return
            if method == 'set':
                FakeDsmState.set_calls.append(dict(params))
                self._send({'success': True, 'data': {'name': params.get('name')}})
                return
        if path == '/webapi/entry.cgi' and api == 'SYNO.Core.User.PasswordPolicy':
            self._send({
                'success': True,
                'data': {
                    'password_must_change': False,
                    'strong_password': {
                        'min_length': 10,
                        'min_length_enable': True,
                        'mixed_case': True,
                        'included_numeric_char': True,
                        'included_special_char': True,
                        'exclude_username': True,
                        'history_num': 3,
                    },
                },
            })
            return
        self._send({'success': False, 'error': {'code': 102}})


class TestStandaloneScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), FakeDsmHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f'http://127.0.0.1:{cls.server.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeDsmState.set_calls = []
        FakeDsmState.login_attempts = []
        FakeDsmState.fail_login_code = None
        FakeDsmState.fail_list_with_2fa = False
        FakeDsmState.logout_calls = []
        os.environ['TEST_ADMIN_PASSWORD'] = 'admin-secret'
        os.environ['TEST_NEW_PASSWORD'] = 'Str0ng!Passw0rd'

    def _client(self):
        client = syno.DsmClient(self.base_url, verify_ssl=False, timeout=5)
        client.login('admin', 'admin-secret')
        return client

    # -- 基础函数 ---------------------------------------------------------

    def test_normalize_base_url(self):
        self.assertEqual(
            syno.normalize_base_url('192.168.1.10', 5001, True),
            'https://192.168.1.10:5001',
        )
        self.assertEqual(
            syno.normalize_base_url('https://nas.local:5002', 5001, True),
            'https://nas.local:5002',
        )
        with self.assertRaises(ValueError):
            syno.normalize_base_url('https://nas.local/dsm', 5001, True)
        with self.assertRaises(ValueError):
            syno.normalize_base_url('', 5001, True)

    def test_normalize_user(self):
        user = syno.normalize_user(FakeDsmState.users[0])
        self.assertEqual(user['name'], 'alice')
        self.assertTrue(user['groups_known'])
        self.assertFalse(user['is_admin'])
        self.assertTrue(user['two_factor'])
        self.assertEqual(user['password_last_change'], '2024-03-07')
        admin = syno.normalize_user(FakeDsmState.users[1])
        self.assertTrue(admin['is_admin'])

    def test_password_policy(self):
        policy = syno.normalize_password_policy({
            'strong_password': {
                'min_length': 10, 'min_length_enable': True, 'mixed_case': True,
                'included_numeric_char': True, 'included_special_char': True,
                'exclude_username': True,
            }
        })
        self.assertEqual(syno.validate_password('Str0ng!Passw0rd', policy), [])
        self.assertTrue(syno.validate_password('weak', policy))
        self.assertTrue(syno.validate_password('alice!Passw0rd', policy, 'alice'))

    # -- 客户端 -----------------------------------------------------------

    def test_login_list_set_logout(self):
        client = self._client()
        users = client.list_users()
        self.assertEqual([u['name'] for u in users], ['alice', 'admin', 'guest'])
        self.assertTrue(users[1]['is_admin'])

        client.set_user_password('alice', 'Str0ng!Passw0rd')
        self.assertEqual(len(FakeDsmState.set_calls), 1)
        params = FakeDsmState.set_calls[0]
        self.assertEqual(params['name'], 'alice')
        self.assertEqual(params['new_name'], 'alice')
        self.assertEqual(params['password'], 'Str0ng!Passw0rd')
        self.assertEqual(params['description'], '财务部')
        self.assertEqual(params['email'], 'alice@example.com')
        self.assertEqual(params['expired'], 'normal')
        self.assertEqual(params['cannot_chg_passwd'], 'false')
        self.assertEqual(params['passwd_never_expire'], 'true')
        self.assertEqual(params['_sid'], 'FAKE-SID')

        client.logout()
        self.assertEqual(len(FakeDsmState.logout_calls), 1)
        self.assertEqual(FakeDsmState.logout_calls[0]['_sid'], 'FAKE-SID')
        self.assertIsNone(client.sid)

    def test_login_2fa_required(self):
        FakeDsmState.fail_login_code = 403
        client = syno.DsmClient(self.base_url, verify_ssl=False, timeout=5)
        with self.assertRaises(syno.DsmAuthError) as ctx:
            client.login('admin', 'secret')
        self.assertTrue(ctx.exception.requires_otp)

    def test_list_fallback_without_2fa(self):
        FakeDsmState.fail_list_with_2fa = True
        client = self._client()
        users = client.list_users()
        self.assertEqual(len(users), 3)
        # 降级后仍保留 groups 字段，管理员识别不受影响
        self.assertTrue(users[1]['is_admin'])

    def test_set_aborts_if_attributes_missing(self):
        client = self._client()
        original = FakeDsmState.users[0].copy()
        FakeDsmState.users[0].pop('expired')
        try:
            with self.assertRaises(syno.DsmAPIError) as ctx:
                client.set_user_password('alice', 'Str0ng!Passw0rd')
            self.assertIn('中止', str(ctx.exception))
        finally:
            FakeDsmState.users[0] = original

    # -- 命令行 -----------------------------------------------------------

    def test_cli_list_json(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = syno.main([
                'list', '--host', self.base_url, '--account', 'admin',
                '--password-env', 'TEST_ADMIN_PASSWORD', '--json',
            ])
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data[0]['name'], 'alice')

    def test_cli_reset_dry_run(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = syno.main([
                'reset', '--host', self.base_url, '--account', 'admin',
                '--password-env', 'TEST_ADMIN_PASSWORD',
                '--new-password-env', 'TEST_NEW_PASSWORD',
                '--users', 'alice', '--dry-run', '--yes',
            ])
        self.assertEqual(code, 0)
        self.assertEqual(FakeDsmState.set_calls, [])
        self.assertIn('预演', out.getvalue())

    def test_cli_reset_actual(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = syno.main([
                'reset', '--host', self.base_url, '--account', 'admin',
                '--password-env', 'TEST_ADMIN_PASSWORD',
                '--new-password-env', 'TEST_NEW_PASSWORD',
                '--users', 'alice', '--yes',
                '--audit-log', os.path.join(os.environ['TEMP'], 'syno_audit_test.csv'),
            ])
        self.assertEqual(code, 0)
        self.assertEqual([call['name'] for call in FakeDsmState.set_calls], ['alice'])
        self.assertIn('成功', out.getvalue())
        audit_path = os.path.join(os.environ['TEMP'], 'syno_audit_test.csv')
        if os.path.exists(audit_path):
            os.remove(audit_path)

    def test_cli_blocks_admin_without_flag(self):
        with self.assertRaises(SystemExit) as ctx:
            syno.main([
                'reset', '--host', self.base_url, '--account', 'admin',
                '--password-env', 'TEST_ADMIN_PASSWORD',
                '--new-password-env', 'TEST_NEW_PASSWORD',
                '--users', 'admin', '--yes',
            ])
        self.assertIn('管理员', str(ctx.exception))

    def test_resolve_targets_all_excludes_guest_and_self(self):
        users = [syno.normalize_user(item) for item in FakeDsmState.users]
        targets = syno.resolve_targets(users, 'admin', None, True)
        self.assertEqual([u['name'] for u in targets], ['alice'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
