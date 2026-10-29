"""群晖用户扫描 / 批量改密测试。

测试不连接真实 NAS，全部使用假 HTTP 会话和假 DSM 客户端。
覆盖：
1. 地址规范化、主机白名单
2. 用户数据规范化、密码策略校验
3. DSM API 请求参数、错误码、会话失效
4. 改密时保留用户原有属性（防止覆盖描述/邮箱/过期时间）
5. Flask 路由：CSRF、连接、筛选、批量改密、管理员保护、审计、CSV 导出
"""

import json
import os
import re
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import NasPasswordResetLog
from app.routes import nas_users as nas_routes
from app.services.synology_service import (
    NasSessionStore,
    SynologyAPIError,
    SynologyAuthError,
    SynologyClient,
    SynologySessionExpired,
    default_password_policy,
    host_allowed,
    normalize_base_url,
    normalize_password_policy,
    normalize_user,
    validate_password,
)


# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {'Content-Type': 'application/json'}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class StubHttpSession:
    """记录请求并返回预设响应。"""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, **kwargs):
        self.calls.append(('GET', url, dict(params or {})))
        return self.handler('GET', url, dict(params or {}))

    def post(self, url, data=None, **kwargs):
        self.calls.append(('POST', url, dict(data or {})))
        return self.handler('POST', url, dict(data or {}))


def make_dsm_handler(state=None):
    state = state if state is not None else {}
    state.setdefault('users', [
        {
            'name': 'alice',
            'description': '财务部',
            'email': 'alice@example.com',
            'groups': ['users'],
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
    ])

    def handler(method, url, params):
        api = params.get('api')
        if 'query.cgi' in url and api == 'SYNO.API.Info':
            return FakeResponse({
                'success': True,
                'data': {
                    'SYNO.API.Auth': {'path': 'auth.cgi', 'minVersion': 1, 'maxVersion': 6},
                    'SYNO.Core.User': {'path': 'entry.cgi', 'minVersion': 1, 'maxVersion': 1},
                    'SYNO.Core.User.PasswordPolicy': {'path': 'entry.cgi', 'minVersion': 1, 'maxVersion': 1},
                },
            })
        if 'auth.cgi' in url and api == 'SYNO.API.Auth':
            if params.get('method') == 'login':
                state['login_attempts'] = state.get('login_attempts', 0) + 1
                if state.get('fail_login'):
                    return FakeResponse({'success': False, 'error': {'code': state['fail_login']}})
                return FakeResponse({'success': True, 'data': {'sid': 'TEST-SID'}})
            return FakeResponse({'success': True, 'data': {}})
        if api == 'SYNO.Core.User':
            if params.get('method') == 'list':
                if state.get('fail_list_with_2fa') and '2fa_status' in params.get('additional', ''):
                    return FakeResponse({'success': False, 'error': {'code': 101}})
                return FakeResponse({'success': True, 'data': {'users': state['users'], 'total': len(state['users'])}})
            if params.get('method') == 'get':
                name = params.get('name')
                for user in state['users']:
                    if user['name'] == name:
                        return FakeResponse({'success': True, 'data': {'users': [user]}})
                return FakeResponse({'success': False, 'error': {'code': 102}})
            if params.get('method') == 'set':
                state.setdefault('set_calls', []).append(dict(params))
                if state.get('expire_session_on_set'):
                    return FakeResponse({'success': False, 'error': {'code': 106}})
                return FakeResponse({'success': True, 'data': {'name': params.get('name')}})
        if api == 'SYNO.Core.User.PasswordPolicy':
            return FakeResponse({
                'success': True,
                'data': {
                    'password_must_change': False,
                    'strong_password': {
                        'min_length': 8,
                        'min_length_enable': True,
                        'mixed_case': True,
                        'included_numeric_char': True,
                        'included_special_char': True,
                        'exclude_username': True,
                        'history_num': 3,
                    },
                },
            })
        return FakeResponse({'success': False, 'error': {'code': 102}})

    return handler, state


class FakeClient:
    """替换 SynologyClient 的路由测试替身。"""

    instances = []

    def __init__(self, base_url, verify_ssl=True, timeout=20):
        self.base_url = base_url
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.account = None
        self.logged_out = False
        self.password_calls = []
        self.fail_login_code = None
        self.session_expired = False
        self.users = [
            {
                'name': 'alice', 'uid': 1001, 'description': '财务部', 'email': 'alice@example.com',
                'groups': ['users'], 'groups_known': True, 'is_admin': False, 'is_guest': False, 'is_builtin': False,
                'expired': 'normal', 'cannot_chg_passwd': False, 'passwd_never_expire': True,
                'password_last_change': '2024-03-07', 'two_factor': True, 'two_factor_raw': 'enabled',
                'raw': {
                    'expired': 'normal', 'description': '财务部', 'email': 'alice@example.com',
                    'cannot_chg_passwd': False, 'passwd_never_expire': True,
                },
            },
            {
                'name': 'admin', 'uid': 1000, 'description': '管理员', 'email': 'admin@example.com',
                'groups': ['users', 'administrators'], 'groups_known': True, 'is_admin': True, 'is_guest': False,
                'is_builtin': True, 'expired': 'now', 'cannot_chg_passwd': False,
                'passwd_never_expire': True, 'password_last_change': '2024-03-07',
                'two_factor': False, 'two_factor_raw': 'disabled',
                'raw': {
                    'expired': 'now', 'description': '管理员', 'email': 'admin@example.com',
                    'cannot_chg_passwd': False, 'passwd_never_expire': True,
                },
            },
            {
                'name': 'guest', 'uid': 1002, 'description': 'Guest', 'email': '',
                'groups': ['users'], 'groups_known': True, 'is_admin': False, 'is_guest': True, 'is_builtin': True,
                'expired': 'now', 'cannot_chg_passwd': False, 'passwd_never_expire': True,
                'password_last_change': None, 'two_factor': False, 'two_factor_raw': 'disabled',
                'raw': {
                    'expired': 'now', 'description': 'Guest', 'email': '',
                    'cannot_chg_passwd': False, 'passwd_never_expire': True,
                },
            },
        ]
        FakeClient.instances.append(self)

    def login(self, account, password, otp_code=None):
        if self.fail_login_code:
            raise SynologyAuthError(
                '需要动态验证码', code=self.fail_login_code,
                requires_otp=self.fail_login_code in (403, 406),
            )
        if not account or not password:
            raise SynologyAuthError('账号或密码不能为空')
        self.account = account
        return 'TEST-SID'

    def list_users(self):
        return list(self.users)

    def get_password_policy(self):
        policy = default_password_policy()
        policy.update({
            'available': True, 'min_length': 8, 'min_length_enable': True,
            'mixed_case': True, 'included_numeric_char': True,
            'included_special_char': True, 'exclude_username': True, 'history_num': 3,
        })
        return policy

    def get_user(self, name):
        for user in self.users:
            if user['name'] == name:
                return user
        raise SynologyAPIError('未找到用户')

    def set_user_password(self, name, password, current=None):
        if self.session_expired:
            raise SynologySessionExpired('DSM 会话已过期')
        if not any(user['name'] == name for user in self.users):
            raise SynologyAPIError('未找到用户')
        self.password_calls.append(name)
        return {'name': name}

    def logout(self):
        self.logged_out = True


def extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    if not match:
        raise AssertionError('页面中未找到 csrf_token')
    return match.group(1)


# ---------------------------------------------------------------------------
# 基础函数
# ---------------------------------------------------------------------------


class TestNormalizeBaseUrl(unittest.TestCase):
    def test_ip_default_https_5001(self):
        self.assertEqual(
            normalize_base_url('192.168.1.10', 5001, True),
            ('https://192.168.1.10:5001', '192.168.1.10', 5001),
        )

    def test_domain_with_scheme(self):
        self.assertEqual(
            normalize_base_url('https://nas.example.com:5002', 5001, True),
            ('https://nas.example.com:5002', 'nas.example.com', 5002),
        )

    def test_http_explicit_port(self):
        self.assertEqual(
            normalize_base_url('nas.local:5000', 5001, False),
            ('http://nas.local:5000', 'nas.local', 5000),
        )

    def test_ipv6(self):
        self.assertEqual(
            normalize_base_url('[fd00::1]', 5001, True)[0],
            'https://[fd00::1]:5001',
        )

    def test_reject_path(self):
        with self.assertRaises(ValueError):
            normalize_base_url('https://nas.local/dsm', 5001, True)

    def test_reject_credentials(self):
        with self.assertRaises(ValueError):
            normalize_base_url('https://user:pass@nas.local', 5001, True)

    def test_reject_bad_port(self):
        with self.assertRaises(ValueError):
            normalize_base_url('nas.local', 70000, True)

    def test_empty(self):
        with self.assertRaises(ValueError):
            normalize_base_url('  ', 5001, True)


class TestHostAllowlist(unittest.TestCase):
    def test_empty_allows_all(self):
        self.assertTrue(host_allowed('any.example.com', []))

    def test_exact(self):
        self.assertTrue(host_allowed('nas1.local', ['nas1.local']))
        self.assertFalse(host_allowed('nas2.local', ['nas1.local']))

    def test_suffix(self):
        self.assertTrue(host_allowed('nas1.corp.local', ['.corp.local']))
        self.assertTrue(host_allowed('corp.local', ['.corp.local']))
        self.assertFalse(host_allowed('evilcorp.local', ['.corp.local']))


class TestNormalizeUser(unittest.TestCase):
    def test_groups_and_admin(self):
        user = normalize_user({
            'name': 'alice', 'groups': [{'name': 'users'}, {'name': 'administrators'}],
            'expired': 'normal', 'cannot_chg_passwd': 0, 'passwd_never_expire': 1,
        })
        self.assertTrue(user['is_admin'])
        self.assertTrue(user['groups_known'])
        self.assertEqual(user['groups'], ['users', 'administrators'])
        self.assertFalse(user['cannot_chg_passwd'])
        self.assertTrue(user['passwd_never_expire'])

    def test_groups_json_string(self):
        user = normalize_user({'name': 'bob', 'groups': '["users", "backup"]'})
        self.assertEqual(user['groups'], ['users', 'backup'])

    def test_last_change_days(self):
        self.assertEqual(normalize_user({'name': 'bob', 'password_last_change': 19789})['password_last_change'], '2024-03-07')

    def test_last_change_empty(self):
        self.assertIsNone(normalize_user({'name': 'bob', 'password_last_change': 0})['password_last_change'])

    def test_two_factor(self):
        self.assertTrue(normalize_user({'name': 'bob', '2fa_status': 'enabled'})['two_factor'])
        self.assertFalse(normalize_user({'name': 'bob', '2fa_status': 'disabled'})['two_factor'])
        self.assertIsNone(normalize_user({'name': 'bob'})['two_factor'])

    def test_missing_name(self):
        with self.assertRaises(ValueError):
            normalize_user({'description': 'x'})


class TestPasswordPolicy(unittest.TestCase):
    def setUp(self):
        self.policy = normalize_password_policy({
            'strong_password': {
                'min_length': 10, 'min_length_enable': True, 'mixed_case': True,
                'included_numeric_char': True, 'included_special_char': True,
                'exclude_username': True, 'history_num': 5,
            }
        })

    def test_valid(self):
        self.assertEqual(validate_password('Str0ng!Pass', self.policy, 'alice'), [])

    def test_too_short(self):
        errors = validate_password('Sh0rt!', self.policy, 'alice')
        self.assertTrue(any('至少' in item for item in errors))

    def test_missing_cases(self):
        errors = validate_password('alllower1!xx', self.policy, 'alice')
        self.assertTrue(any('大写' in item for item in errors))

    def test_missing_digit(self):
        errors = validate_password('NoDigits!Here', self.policy, 'alice')
        self.assertTrue(any('数字' in item for item in errors))

    def test_missing_special(self):
        errors = validate_password('NoSpecial1234', self.policy, 'alice')
        self.assertTrue(any('特殊字符' in item for item in errors))

    def test_contains_username(self):
        errors = validate_password('Alice!Pass99', self.policy, 'alice')
        self.assertTrue(any('用户名' in item for item in errors))

    def test_empty(self):
        self.assertEqual(validate_password('', self.policy), ['新密码不能为空'])

    def test_default_policy(self):
        policy = default_password_policy()
        self.assertFalse(policy['available'])
        self.assertEqual(validate_password('Abcd1234', policy), [])


# ---------------------------------------------------------------------------
# DSM 客户端
# ---------------------------------------------------------------------------


class TestSynologyClient(unittest.TestCase):
    def _client(self, state=None):
        handler, state = make_dsm_handler(state)
        session = StubHttpSession(handler)
        client = SynologyClient('https://nas.local:5001', verify_ssl=False, http_session=session)
        return client, session, state

    def test_login_and_list_users(self):
        client, session, state = self._client()
        self.assertEqual(client.login('admin', 'secret'), 'TEST-SID')
        users = client.list_users()
        self.assertEqual([user['name'] for user in users], ['alice', 'admin'])
        self.assertTrue(users[1]['is_admin'])
        list_call = next(call for call in session.calls if call[2].get('method') == 'list')
        self.assertEqual(list_call[2]['_sid'], 'TEST-SID')
        self.assertEqual(list_call[2]['type'], 'local')
        self.assertIn('groups', list_call[2]['additional'])

    def test_login_otp_required(self):
        client, _session, _state = self._client({'fail_login': 403})
        with self.assertRaises(SynologyAuthError) as ctx:
            client.login('admin', 'secret')
        self.assertTrue(ctx.exception.requires_otp)
        self.assertEqual(ctx.exception.code, 403)

    def test_login_version_fallback(self):
        attempts = []

        def handler(method, url, params):
            if 'query.cgi' in url:
                return FakeResponse({'success': True, 'data': {
                    'SYNO.API.Auth': {'path': 'auth.cgi', 'minVersion': 1, 'maxVersion': 6},
                }})
            if 'auth.cgi' in url:
                attempts.append(int(params.get('version')))
                if str(params.get('version')) == '6':
                    return FakeResponse({'success': False, 'error': {'code': 104}})
                return FakeResponse({'success': True, 'data': {'sid': 'OLD-SID'}})
            return FakeResponse({'success': False, 'error': {'code': 102}})

        session = StubHttpSession(handler)
        client = SynologyClient('https://nas.local:5001', http_session=session)
        self.assertEqual(client.login('admin', 'secret'), 'OLD-SID')
        self.assertEqual(attempts, [6, 5])

    def test_list_users_fallback_without_2fa(self):
        client, _session, state = self._client({'fail_list_with_2fa': True})
        client.login('admin', 'secret')
        users = client.list_users()
        self.assertEqual(len(users), 2)
        self.assertEqual(users[0]['groups'], ['users'])

    def test_set_password_preserves_attributes(self):
        client, session, _state = self._client()
        client.login('admin', 'secret')
        client.set_user_password('alice', 'NewPass123!')
        set_call = next(call for call in session.calls if call[2].get('method') == 'set')
        params = set_call[2]
        self.assertEqual(params['name'], 'alice')
        self.assertEqual(params['new_name'], 'alice')
        self.assertEqual(params['password'], 'NewPass123!')
        self.assertEqual(params['description'], '财务部')
        self.assertEqual(params['email'], 'alice@example.com')
        self.assertEqual(params['expired'], 'normal')
        self.assertEqual(params['cannot_chg_passwd'], 'false')
        self.assertEqual(params['passwd_never_expire'], 'true')
        self.assertEqual(params['notify_by_email'], 'false')
        self.assertEqual(params['send_password'], 'false')
        self.assertEqual(params['_sid'], 'TEST-SID')

    def test_set_password_aborts_when_attributes_missing(self):
        client, _session, state = self._client()
        state['users'][0].pop('expired')
        client.login('admin', 'secret')
        with self.assertRaises(SynologyAPIError) as ctx:
            client.set_user_password('alice', 'NewPass123!')
        self.assertIn('中止', str(ctx.exception))

    def test_session_expired(self):
        client, _session, state = self._client()
        client.login('admin', 'secret')
        state['expire_session_on_set'] = True
        with self.assertRaises(SynologySessionExpired):
            client.set_user_password('alice', 'NewPass123!')

    def test_api_permission_error(self):
        client, _session, _state = self._client()
        client.login('admin', 'secret')
        # 未知用户返回 102（API 不存在）在此假实现中不是权限问题，改用直接构造
        with self.assertRaises(SynologyAPIError):
            client.get_user('nobody')

    def test_get_password_policy(self):
        client, _session, _state = self._client()
        client.login('admin', 'secret')
        policy = client.get_password_policy()
        self.assertTrue(policy['available'])
        self.assertEqual(policy['min_length'], 8)
        self.assertTrue(policy['included_special_char'])

    def test_invalid_base_url(self):
        with self.assertRaises(ValueError):
            SynologyClient('ftp://nas.local')


# ---------------------------------------------------------------------------
# Flask 路由
# ---------------------------------------------------------------------------


class TestNasRoutes(unittest.TestCase):
    def setUp(self):
        FakeClient.instances.clear()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SECRET_KEY': 'test-secret',
            'NAS_SESSION_TTL': 1800,
            'WTF_CSRF_ENABLED': False,
        })
        self.client = self.app.test_client()
        # 清空全局会话存储，避免测试间串数据
        from app.services.synology_service import nas_session_store
        nas_session_store.clear()

    def _connect(self, account='admin'):
        page = self.client.get('/nas/users/')
        csrf = extract_csrf(page.get_data(as_text=True))
        with patch.object(nas_routes, '_build_client', return_value=FakeClient('https://nas.local:5001')):
            response = self.client.post('/nas/users/connect', data={
                'csrf_token': csrf,
                'host': 'nas.local',
                'port': '5001',
                'use_https': 'on',
                'verify_ssl': 'on',
                'account': account,
                'password': 'secret',
            })
        return response

    def _users_page(self):
        response = self.client.get('/nas/users/')
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_connect_page(self):
        page = self.client.get('/nas/users/')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('连接群晖 NAS', html)
        self.assertIn('name="host"', html)
        self.assertIn('csrf_token', html)

    def test_connect_requires_csrf(self):
        response = self.client.post('/nas/users/connect', data={'host': 'nas.local'})
        self.assertEqual(response.status_code, 400)

    def test_connect_bad_credentials_message(self):
        page = self.client.get('/nas/users/')
        csrf = extract_csrf(page.get_data(as_text=True))
        fake = FakeClient('https://nas.local:5001')
        fake.fail_login_code = 403
        with patch.object(nas_routes, '_build_client', return_value=fake):
            response = self.client.post('/nas/users/connect', data={
                'csrf_token': csrf, 'host': 'nas.local', 'port': '5001',
                'use_https': 'on', 'account': 'admin', 'password': 'bad',
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn('动态验证码', response.get_data(as_text=True))
        self.assertTrue(fake.logged_out)

    def test_connect_and_list(self):
        response = self._connect()
        self.assertEqual(response.status_code, 303)
        html = self._users_page()
        self.assertIn('alice', html)
        self.assertIn('admin', html)
        self.assertIn('财务部', html)
        self.assertIn('批量修改密码', html)

    def test_reset_one_user(self):
        self._connect()
        html = self._users_page()
        csrf = extract_csrf(html)
        fake = FakeClient.instances[-1]
        response = self.client.post('/nas/users/reset', data={
            'csrf_token': csrf,
            'selected': 'alice',
            'new_password': 'Str0ng!Passw0rd',
            'confirm_password': 'Str0ng!Passw0rd',
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(fake.password_calls, ['alice'])
        html = self._users_page()
        self.assertIn('密码已重置', html)
        with self.app.app_context():
            logs = NasPasswordResetLog.query.all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].target_user, 'alice')
            self.assertEqual(logs[0].result, 'success')

    def test_reset_rejects_admin_without_confirmation(self):
        self._connect()
        csrf = extract_csrf(self._users_page())
        fake = FakeClient.instances[-1]
        response = self.client.post('/nas/users/reset', data={
            'csrf_token': csrf,
            'selected': 'admin',
            'new_password': 'Str0ng!Passw0rd',
            'confirm_password': 'Str0ng!Passw0rd',
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(fake.password_calls, [])
        self.assertIn('管理员账号', self._users_page())

    def test_reset_admin_with_confirmation(self):
        self._connect(account='other_admin')
        csrf = extract_csrf(self._users_page())
        fake = FakeClient.instances[-1]
        response = self.client.post('/nas/users/reset', data={
            'csrf_token': csrf,
            'selected': 'admin',
            'new_password': 'Str0ng!Passw0rd',
            'confirm_password': 'Str0ng!Passw0rd',
            'allow_admin': 'on',
            'admin_confirm': 'RESET',
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(fake.password_calls, ['admin'])

    def test_reset_skips_self(self):
        self._connect(account='admin')
        csrf = extract_csrf(self._users_page())
        fake = FakeClient.instances[-1]
        response = self.client.post('/nas/users/reset', data={
            'csrf_token': csrf,
            'selected': 'admin',
            'new_password': 'Str0ng!Passw0rd',
            'confirm_password': 'Str0ng!Passw0rd',
            'allow_admin': 'on',
            'admin_confirm': 'RESET',
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(fake.password_calls, [])
        self.assertIn('不能通过当前登录会话重置自身密码', self._users_page())

    def test_reset_password_policy_rejected(self):
        self._connect()
        csrf = extract_csrf(self._users_page())
        fake = FakeClient.instances[-1]
        response = self.client.post('/nas/users/reset', data={
            'csrf_token': csrf,
            'selected': 'alice',
            'new_password': 'weak',
            'confirm_password': 'weak',
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(fake.password_calls, [])
        self.assertIn('密码策略', self._users_page())

    def test_reset_password_mismatch(self):
        self._connect()
        csrf = extract_csrf(self._users_page())
        response = self.client.post('/nas/users/reset', data={
            'csrf_token': csrf,
            'selected': 'alice',
            'new_password': 'Str0ng!Passw0rd',
            'confirm_password': 'Different1!',
        })
        self.assertEqual(response.status_code, 303)
        self.assertIn('不一致', self._users_page())

    def test_reset_requires_csrf(self):
        self._connect()
        response = self.client.post('/nas/users/reset', data={'selected': 'alice'})
        self.assertEqual(response.status_code, 400)

    def test_unknown_groups_requires_admin_confirmation(self):
        self._connect()
        fake = FakeClient.instances[-1]
        fake.users[0]['groups_known'] = False
        csrf = extract_csrf(self._users_page())
        response = self.client.post('/nas/users/reset', data={
            'csrf_token': csrf,
            'selected': 'alice',
            'new_password': 'Str0ng!Passw0rd',
            'confirm_password': 'Str0ng!Passw0rd',
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(fake.password_calls, [])
        self.assertIn('未返回用户组信息', self._users_page())

    def test_unknown_groups_with_confirmation_succeeds(self):
        self._connect()
        fake = FakeClient.instances[-1]
        fake.users[0]['groups_known'] = False
        csrf = extract_csrf(self._users_page())
        response = self.client.post('/nas/users/reset', data={
            'csrf_token': csrf,
            'selected': 'alice',
            'new_password': 'Str0ng!Passw0rd',
            'confirm_password': 'Str0ng!Passw0rd',
            'allow_admin': 'on',
            'admin_confirm': 'RESET',
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(fake.password_calls, ['alice'])

    def test_filter_users(self):
        self._connect()
        html = self.client.get('/nas/users/?q=alice').get_data(as_text=True)
        self.assertIn('alice', html)
        self.assertNotIn('Guest', html)

    def test_export_csv(self):
        self._connect()
        response = self.client.get('/nas/users/export')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response.content_type)
        body = response.get_data(as_text=True)
        self.assertIn('用户名', body)
        self.assertIn('alice', body)
        self.assertIn('\ufeff', body)

    def test_disconnect(self):
        self._connect()
        csrf = extract_csrf(self._users_page())
        fake = FakeClient.instances[-1]
        response = self.client.post('/nas/users/disconnect', data={'csrf_token': csrf})
        self.assertEqual(response.status_code, 303)
        self.assertTrue(fake.logged_out)
        html = self._users_page()
        self.assertIn('连接群晖 NAS', html)


class TestSessionStore(unittest.TestCase):
    def test_expiry(self):
        store = NasSessionStore(ttl=60)
        fake = FakeClient('https://nas.local:5001')
        item = store.create(
            client=fake, host='nas.local', base_url='https://nas.local:5001',
            account='admin', users=[], policy=default_password_policy(),
        )
        self.assertIsNotNone(store.get(item.token))
        # 直接回拨时间模拟超时
        item.last_seen -= 61
        self.assertIsNone(store.get(item.token))

    def test_drop_logs_out(self):
        store = NasSessionStore(ttl=60)
        fake = FakeClient('https://nas.local:5001')
        item = store.create(
            client=fake, host='nas.local', base_url='https://nas.local:5001',
            account='admin', users=[], policy=default_password_policy(),
        )
        store.drop(item.token)
        self.assertTrue(fake.logged_out)
        self.assertIsNone(store.get(item.token))


if __name__ == '__main__':
    unittest.main(verbosity=2)
