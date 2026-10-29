"""监控服务层"""
from app.extensions import db
from app.models import AttackEvent, ConfigChange, DesktopTicket, DeviceAsset


class MonitorService:
    """监控指标业务逻辑"""

    @staticmethod
    def check_db():
        """检查数据库连通性"""
        try:
            db.session.execute('SELECT 1')
            return True
        except Exception:
            return False

    @staticmethod
    def get_app_counts():
        """获取各模块计数"""
        return {
            'attack_events': AttackEvent.query.count(),
            'config_changes': ConfigChange.query.count(),
            'tickets': DesktopTicket.query.count(),
            'devices': DeviceAsset.query.count(),
        }

    @staticmethod
    def get_db_info():
        """获取数据库元信息"""
        return {
            'tables': ['attack_events', 'config_changes', 'desktop_tickets',
                        'device_assets', 'quick_links', 'ip_scan_results'],
            'engine': 'sqlite'
        }