"""健康检查与监控端点（委托到服务层）"""
from flask import Blueprint, jsonify
import psutil
import platform
from datetime import datetime
from app.services import MonitorService

monitor_bp = Blueprint('monitor', __name__, url_prefix='/monitor')


@monitor_bp.route('/health')
def health_check():
    """基础健康检查"""
    db_ok = MonitorService.check_db()
    return jsonify({
        'status': 'healthy' if db_ok else 'unhealthy',
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'service': 'ops-manager',
        'version': 'V1.4',
        'database': 'connected' if db_ok else 'disconnected'
    }), 200 if db_ok else 503


@monitor_bp.route('/metrics')
def metrics():
    """应用性能指标"""
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    counts = MonitorService.get_app_counts()
    db_info = MonitorService.get_db_info()

    return jsonify({
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'system': {
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'memory_available_gb': round(memory.available / (1024**3), 2),
            'disk_percent': disk.percent,
            'disk_free_gb': round(disk.free / (1024**3), 2),
            'platform': platform.platform(),
            'python_version': platform.python_version(),
        },
        'application': {
            'attack_events': counts['attack_events'],
            'config_changes': counts['config_changes'],
            'tickets': counts['tickets'],
            'devices': counts['devices'],
            'uptime': 'N/A',
        },
        'database': db_info
    })


@monitor_bp.route('/info')
def app_info():
    """应用信息"""
    return jsonify({
        'name': '运维管理系统',
        'version': 'V1.4',
        'description': '企业级运维管理平台',
        'author': '运维团队',
        'license': '内部使用',
        'repository': '内部 Git',
        'built_at': '2026-05-24',
        'tech_stack': [
            'Python 3.11+',
            'Flask 3.0',
            'SQLAlchemy 2.0',
            'SQLite',
            'Bootstrap 5',
            'Chart.js'
        ],
        'features': [
            '攻击事件管理',
            '配置变更管理',
            '运维工单管理',
            '设备资产管理',
            'IP 存活扫描',
            '安全事件中心',
            '周报/月报生成',
            '中控大屏'
        ]
    })