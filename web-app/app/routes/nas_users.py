"""群晖 NAS 用户扫描与批量改密路由。

安全约定：
- 管理员密码只用于当次登录，不落库、不写日志、不回显。
- DSM SID 保存在进程内 ``nas_session_store``，浏览器只持有随机 token。
- 所有写操作都校验 CSRF token。
- 批量改密逐用户读取当前属性，避免覆盖描述、邮箱、过期时间等设置。
"""

from __future__ import annotations

import csv
import hmac
import io
import secrets
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.extensions import db
from app.models import NasPasswordResetLog
from app.services.synology_service import (
    NasSession,
    SynologyAuthError,
    SynologyClient,
    SynologyError,
    SynologySessionExpired,
    csv_safe,
    host_allowed,
    nas_session_store,
    normalize_base_url,
    validate_password,
)

nas_users_bp = Blueprint('nas_users', __name__, url_prefix='/nas/users')

SESSION_TOKEN_KEY = 'nas_session_token'
CONNECT_CSRF_KEY = 'nas_connect_csrf'


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _new_connect_csrf() -> str:
    token = secrets.token_urlsafe(32)
    session[CONNECT_CSRF_KEY] = token
    return token


def _get_connect_csrf() -> str:
    token = session.get(CONNECT_CSRF_KEY)
    if not token:
        token = _new_connect_csrf()
    return token


def _check_connect_csrf() -> None:
    expected = session.get(CONNECT_CSRF_KEY)
    supplied = request.form.get('csrf_token', '')
    if not expected or not supplied or not hmac.compare_digest(str(expected), str(supplied)):
        abort(400, description='页面已过期或 CSRF 校验失败，请刷新后重试。')


def _check_csrf(conn: NasSession) -> None:
    supplied = request.form.get('csrf_token', '')
    if not supplied or not hmac.compare_digest(str(conn.csrf_token), str(supplied)):
        abort(400, description='页面已过期或 CSRF 校验失败，请刷新后重试。')


def _get_conn() -> NasSession | None:
    token = session.get(SESSION_TOKEN_KEY)
    return nas_session_store.get(token)


def _build_client(base_url: str, verify_ssl: bool) -> SynologyClient:
    """独立函数便于测试替换。"""
    return SynologyClient(base_url, verify_ssl=verify_ssl, timeout=20)


def _client_ip() -> str:
    return (request.remote_addr or '')[:64]


def _filter_users(users, q: str, group: str, flag: str):
    q_lower = q.strip().lower()
    result = []
    for user in users:
        if q_lower:
            haystack = ' '.join(
                [
                    str(user.get('name', '')),
                    str(user.get('description', '')),
                    str(user.get('email', '')),
                    ' '.join(user.get('groups') or []),
                ]
            ).lower()
            if q_lower not in haystack:
                continue
        if group and group not in (user.get('groups') or []):
            continue
        if flag == 'admin' and not user.get('is_admin'):
            continue
        if flag == 'guest' and not user.get('is_guest'):
            continue
        if flag == '2fa' and not user.get('two_factor'):
            continue
        if flag == 'cannot_change' and not user.get('cannot_chg_passwd'):
            continue
        if flag == 'never_expire' and not user.get('passwd_never_expire'):
            continue
        result.append(user)
    return result


def _stats(users):
    return {
        'total': len(users),
        'admins': sum(1 for user in users if user.get('is_admin')),
        'two_factor': sum(1 for user in users if user.get('two_factor')),
        'cannot_change': sum(1 for user in users if user.get('cannot_chg_passwd')),
        'never_expire': sum(1 for user in users if user.get('passwd_never_expire')),
    }


def _audit_rows(conn: NasSession, limit: int = 20):
    return (
        NasPasswordResetLog.query
        .filter(NasPasswordResetLog.nas_host == conn.host)
        .order_by(NasPasswordResetLog.created_at.desc(), NasPasswordResetLog.id.desc())
        .limit(limit)
        .all()
    )


def _add_audit(conn: NasSession, target: str, result: str, message: str) -> None:
    db.session.add(
        NasPasswordResetLog(
            nas_host=conn.host[:255],
            nas_account=conn.account[:128],
            target_user=target[:128],
            result=result[:16],
            message=(message or '')[:512],
            client_ip=_client_ip(),
        )
    )


def _render_connect(error: str | None = None, form: dict | None = None):
    form = form or {}
    return render_template(
        'nas_connect.html',
        error=error,
        form=form,
        csrf_token=_get_connect_csrf(),
        default_verify_ssl=bool(current_app.config.get('NAS_DEFAULT_VERIFY_SSL', True)),
        allowed_hosts=current_app.config.get('NAS_ALLOWED_HOSTS') or [],
    )


def _render_users(conn: NasSession):
    q = request.args.get('q', '').strip()
    group = request.args.get('group', '').strip()
    flag = request.args.get('flag', '').strip()
    filtered = _filter_users(conn.users, q, group, flag)
    all_groups = sorted({name for user in conn.users for name in (user.get('groups') or [])})
    groups_unknown = any(not user.get('groups_known', True) for user in conn.users)
    return render_template(
        'nas_users.html',
        conn=conn,
        users=filtered,
        stats=_stats(conn.users),
        groups=all_groups,
        groups_unknown=groups_unknown,
        q=q,
        group=group,
        flag=flag,
        csrf_token=conn.csrf_token,
        batch_result=conn.get_batch_result(),
        audit_rows=_audit_rows(conn),
        max_batch=int(current_app.config.get('NAS_MAX_BATCH', 500)),
    )


# ---------------------------------------------------------------------------
# 页面与连接
# ---------------------------------------------------------------------------


@nas_users_bp.route('/', methods=['GET'])
def index():
    conn = _get_conn()
    if not conn:
        return _render_connect()
    return _render_users(conn)


@nas_users_bp.route('/connect', methods=['POST'])
def connect():
    _check_connect_csrf()

    form = {
        'host': request.form.get('host', '').strip(),
        'port': request.form.get('port', '5001').strip() or '5001',
        'account': request.form.get('account', '').strip(),
        'use_https': 'use_https' in request.form,
        'verify_ssl': 'verify_ssl' in request.form,
    }
    password = request.form.get('password', '')
    otp_code = request.form.get('otp_code', '').strip()

    if not form['host'] or not form['account'] or not password:
        return _render_connect('NAS 地址、管理员账号和密码均为必填项。', form)

    try:
        port = int(form['port'])
    except (TypeError, ValueError):
        return _render_connect('端口必须是 1-65535 之间的数字。', form)

    try:
        base_url, hostname, _port = normalize_base_url(form['host'], port, form['use_https'])
    except ValueError as exc:
        return _render_connect(str(exc), form)

    if not host_allowed(hostname, current_app.config.get('NAS_ALLOWED_HOSTS')):
        return _render_connect('该 NAS 地址不在 NAS_ALLOWED_HOSTS 白名单中。', form)

    client = _build_client(base_url, form['verify_ssl'])
    try:
        client.login(form['account'], password, otp_code or None)
        users = client.list_users()
        policy = client.get_password_policy()
    except SynologyAuthError as exc:
        try:
            client.logout()
        except SynologyError:
            pass
        message = str(exc)
        if exc.requires_otp:
            message += ' 请在“动态验证码”中填写 6 位验证码后重试。'
        current_app.logger.warning(
            '群晖登录失败 host=%s account=%s code=%s', hostname, form['account'], exc.code
        )
        return _render_connect(message, form)
    except SynologyError as exc:
        try:
            client.logout()
        except SynologyError:
            pass
        current_app.logger.warning(
            '群晖扫描失败 host=%s account=%s error=%s', hostname, form['account'], exc
        )
        return _render_connect(str(exc), form)

    old_token = session.get(SESSION_TOKEN_KEY)
    if old_token:
        nas_session_store.drop(old_token)

    item = nas_session_store.create(
        client=client,
        host=hostname,
        base_url=base_url,
        account=form['account'],
        users=users,
        policy=policy,
    )
    session[SESSION_TOKEN_KEY] = item.token
    session.pop(CONNECT_CSRF_KEY, None)
    flash(
        f'已连接 {hostname}，共扫描到 {len(users)} 个本地用户。'
        + ('' if policy.get('available') else '（未能读取密码策略，将使用默认规则校验）'),
        'success',
    )
    return redirect(url_for('nas_users.index'), code=303)


@nas_users_bp.route('/disconnect', methods=['POST'])
def disconnect():
    conn = _get_conn()
    if not conn:
        session.pop(SESSION_TOKEN_KEY, None)
        return redirect(url_for('nas_users.index'), code=303)
    _check_csrf(conn)
    host = conn.host
    nas_session_store.drop(conn.token)
    session.pop(SESSION_TOKEN_KEY, None)
    flash(f'已断开与 {host} 的连接，并注销 DSM 会话。', 'success')
    return redirect(url_for('nas_users.index'), code=303)


@nas_users_bp.route('/refresh', methods=['POST'])
def refresh():
    conn = _get_conn()
    if not conn:
        return redirect(url_for('nas_users.index'), code=303)
    _check_csrf(conn)
    try:
        conn.users = conn.client.list_users()
        conn.policy = conn.client.get_password_policy()
        conn.scan_at = datetime.now()
        conn.set_batch_result(None)
        flash(f'重新扫描完成，共 {len(conn.users)} 个本地用户。', 'success')
    except SynologySessionExpired:
        nas_session_store.drop(conn.token, logout=False)
        session.pop(SESSION_TOKEN_KEY, None)
        flash('DSM 会话已过期，请重新登录 NAS。', 'danger')
    except SynologyError as exc:
        flash(f'扫描失败：{exc}', 'danger')
    return redirect(url_for('nas_users.index'), code=303)


@nas_users_bp.route('/result/clear', methods=['POST'])
def clear_result():
    conn = _get_conn()
    if not conn:
        return redirect(url_for('nas_users.index'), code=303)
    _check_csrf(conn)
    conn.set_batch_result(None)
    return redirect(url_for('nas_users.index'), code=303)


# ---------------------------------------------------------------------------
# 批量改密
# ---------------------------------------------------------------------------


@nas_users_bp.route('/reset', methods=['POST'])
def reset_passwords():
    conn = _get_conn()
    if not conn:
        flash('请先连接 NAS。', 'danger')
        return redirect(url_for('nas_users.index'), code=303)
    _check_csrf(conn)

    selected = []
    for name in request.form.getlist('selected'):
        name = name.strip()
        if name and name not in selected:
            selected.append(name)
    if not selected:
        flash('请至少选择一个用户。', 'danger')
        return redirect(url_for('nas_users.index'), code=303)

    max_batch = int(current_app.config.get('NAS_MAX_BATCH', 500))
    if len(selected) > max_batch:
        flash(f'单次最多重置 {max_batch} 个用户，当前选择了 {len(selected)} 个。', 'danger')
        return redirect(url_for('nas_users.index'), code=303)

    # 改密前重新扫描一次：确保用户仍然存在、管理员标记和密码策略是最新的。
    try:
        conn.users = conn.client.list_users()
        conn.policy = conn.client.get_password_policy()
        conn.scan_at = datetime.now()
    except SynologySessionExpired:
        nas_session_store.drop(conn.token, logout=False)
        session.pop(SESSION_TOKEN_KEY, None)
        flash('DSM 会话已过期，请重新登录 NAS。', 'danger')
        return redirect(url_for('nas_users.index'), code=303)
    except SynologyError as exc:
        flash(f'改密前刷新用户列表失败，已中止操作：{exc}', 'danger')
        return redirect(url_for('nas_users.index'), code=303)

    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    if new_password != confirm_password:
        flash('两次输入的新密码不一致。', 'danger')
        return redirect(url_for('nas_users.index'), code=303)

    errors = validate_password(new_password, conn.policy)
    if errors:
        flash('新密码不符合群晖密码策略：' + '；'.join(errors), 'danger')
        return redirect(url_for('nas_users.index'), code=303)

    allow_admin = 'allow_admin' in request.form
    admin_confirm = request.form.get('admin_confirm', '').strip()
    selected_users = {user['name']: user for user in conn.users}
    admin_selected = [
        name for name in selected
        if selected_users.get(name, {}).get('is_admin')
    ]
    unknown_groups = [
        name for name in selected
        if not selected_users.get(name, {}).get('groups_known', True)
    ]
    must_confirm = bool(admin_selected or unknown_groups)
    if must_confirm and not allow_admin:
        flash(
            '选择中包含管理员账号，或当前 DSM 未返回用户组信息（无法识别管理员），已中止操作。'
            '如确需继续，请勾选“允许重置管理员账号”并输入 RESET 确认。',
            'danger',
        )
        return redirect(url_for('nas_users.index'), code=303)
    if must_confirm and allow_admin and admin_confirm != 'RESET':
        flash('重置管理员或未识别账号需要在确认框中输入 RESET。', 'danger')
        return redirect(url_for('nas_users.index'), code=303)

    started = datetime.now()
    items = []
    session_expired = False

    for name in selected:
        user = selected_users.get(name)
        if not user:
            items.append({'name': name, 'status': 'failed', 'message': '用户不在本次扫描结果中，请刷新后重试'})
            continue
        if name == conn.account:
            items.append({'name': name, 'status': 'skipped', 'message': '不能通过当前登录会话重置自身密码'})
            continue
        if user.get('is_admin') and not allow_admin:
            items.append({'name': name, 'status': 'skipped', 'message': '管理员账号未授权重置'})
            continue

        user_errors = validate_password(new_password, conn.policy, username=name)
        if user_errors:
            items.append({'name': name, 'status': 'failed', 'message': '；'.join(user_errors)})
            continue

        # 会话失效后继续尝试没有意义，把剩余用户标记为跳过
        if session_expired:
            items.append({'name': name, 'status': 'skipped', 'message': 'DSM 会话已失效，未执行'})
            continue

        try:
            # 先读当前属性，再原样回传，避免覆盖描述/邮箱/过期时间。
            # 同时用最新数据再次确认管理员身份，防止扫描后权限发生变化。
            current = conn.client.get_user(name)
            if current.get('is_admin') and not allow_admin:
                items.append({'name': name, 'status': 'skipped', 'message': '该账号当前是管理员，未授权重置'})
                continue
            if current.get('is_admin') and admin_confirm != 'RESET':
                items.append({'name': name, 'status': 'skipped', 'message': '该账号当前是管理员，缺少 RESET 确认'})
                continue
            conn.client.set_user_password(name, new_password, current=current)
            items.append({'name': name, 'status': 'success', 'message': '密码已重置'})
        except SynologySessionExpired as exc:
            session_expired = True
            items.append({'name': name, 'status': 'failed', 'message': str(exc)})
        except SynologyError as exc:
            items.append({'name': name, 'status': 'failed', 'message': str(exc)})
        except Exception as exc:  # pragma: no cover - 防御性兜底
            current_app.logger.exception('重置群晖用户密码时发生未预期错误 user=%s', name)
            items.append({'name': name, 'status': 'failed', 'message': f'内部错误：{exc}'})

    counts = {
        'success': sum(1 for item in items if item['status'] == 'success'),
        'failed': sum(1 for item in items if item['status'] == 'failed'),
        'skipped': sum(1 for item in items if item['status'] == 'skipped'),
    }
    result = {
        'items': items,
        'counts': counts,
        'total': len(items),
        'started_at': started.strftime('%Y-%m-%d %H:%M:%S'),
        'finished_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    conn.set_batch_result(result)

    # 审计日志：只记录结果，绝不记录密码
    for item in items:
        _add_audit(conn, item['name'], item['status'], item['message'])
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('写入群晖改密审计日志失败')

    if session_expired:
        nas_session_store.drop(conn.token, logout=False)
        session.pop(SESSION_TOKEN_KEY, None)
        flash(
            f'批量操作已中止：成功 {counts["success"]}，失败 {counts["failed"]}，'
            f'跳过 {counts["skipped"]}。DSM 会话已过期，请重新登录。',
            'danger',
        )
    elif counts['failed']:
        flash(
            f'批量操作完成：成功 {counts["success"]}，失败 {counts["failed"]}，跳过 {counts["skipped"]}。'
            '请查看下方明细。',
            'danger',
        )
    else:
        flash(
            f'批量操作完成：成功 {counts["success"]}，跳过 {counts["skipped"]}。',
            'success',
        )
    return redirect(url_for('nas_users.index'), code=303)


# ---------------------------------------------------------------------------
# CSV 导出
# ---------------------------------------------------------------------------


@nas_users_bp.route('/export', methods=['GET'])
def export_users():
    conn = _get_conn()
    if not conn:
        flash('请先连接 NAS。', 'danger')
        return redirect(url_for('nas_users.index'), code=303)

    q = request.args.get('q', '').strip()
    group = request.args.get('group', '').strip()
    flag = request.args.get('flag', '').strip()
    users = _filter_users(conn.users, q, group, flag)

    output = io.StringIO(newline='')
    output.write('\ufeff')  # Excel 识别 UTF-8
    writer = csv.writer(output)
    writer.writerow([
        '用户名', '用户组', '管理员', '描述', '邮箱',
        '密码永不过期', '禁止用户改密', '上次改密', '双重验证',
    ])
    for user in users:
        writer.writerow([
            csv_safe(user.get('name')),
            csv_safe(', '.join(user.get('groups') or [])),
            '是' if user.get('is_admin') else '否',
            csv_safe(user.get('description')),
            csv_safe(user.get('email')),
            '是' if user.get('passwd_never_expire') else '否',
            '是' if user.get('cannot_chg_passwd') else '否',
            csv_safe(user.get('password_last_change') or ''),
            '已启用' if user.get('two_factor') else ('未启用' if user.get('two_factor') is False else '未知'),
        ])

    filename = f"synology_users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
