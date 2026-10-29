"""配置备份路由（委托到服务层）"""
from flask import Blueprint, render_template, request, jsonify, current_app
from app.services import ConfigBackupService

config_backup_bp = Blueprint('config_backup', __name__, url_prefix='/config-backup')


@config_backup_bp.route('/')
def backup_page():
    """配置备份页面"""
    page = request.args.get('page', 1, type=int)
    keyword = request.args.get('keyword', '')
    devices = ConfigBackupService.get_switches(page=page, keyword=keyword)
    return render_template('config_backup.html',
                           devices=devices,
                           keyword=keyword)


@config_backup_bp.route('/execute', methods=['POST'])
def backup_execute():
    """执行批量备份"""
    data = request.get_json()
    device_ids = data.get('device_ids', [])
    if not device_ids:
        return jsonify({'success': False, 'message': '未选择任何设备'})

    override = {}
    if data.get('use_global_creds'):
        override['override_protocol'] = data.get('protocol', 'ssh')
        override['override_port'] = int(data.get('port', 22))
        override['override_username'] = data.get('username', '')
        override['override_password'] = data.get('password', '')
    else:
        override['override_protocol'] = None
        override['override_port'] = None
        override['override_username'] = None
        override['override_password'] = None

    results = ConfigBackupService.backup_batch(device_ids, **override)
    return jsonify({'success': True, 'results': results})