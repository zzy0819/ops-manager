"""主页面服务层"""
from datetime import datetime, timedelta
from sqlalchemy import func
from app.extensions import db
from app.models import AttackEvent, ConfigChange, DesktopTicket, DeviceAsset, IPScanResult, QuickLink


class MainService:
    """主页面业务逻辑"""

    @staticmethod
    def get_index_stats():
        """首页统计信息"""
        return {
            'attack_count': AttackEvent.query.count(),
            'config_count': ConfigChange.query.count(),
            'ticket_count': DesktopTicket.query.count(),
            'pending_tickets': DesktopTicket.query.filter(
                DesktopTicket.status.in_(['待处理', '处理中'])
            ).count(),
            'scan_count': IPScanResult.query.count(),
            'device_count': DeviceAsset.query.count(),
            'recent_attacks': AttackEvent.query.order_by(AttackEvent.created_at.desc()).limit(5).all(),
            'recent_configs': ConfigChange.query.order_by(ConfigChange.created_at.desc()).limit(5).all(),
            'recent_tickets': DesktopTicket.query.order_by(DesktopTicket.created_at.desc()).limit(5).all(),
        }

    @staticmethod
    def get_dashboard_data():
        """仪表板完整数据"""
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # 基础统计
        stats = {
            'attack_count': AttackEvent.query.count(),
            'today_attacks': AttackEvent.query.filter(AttackEvent.attack_time >= today_start).count(),
            'config_count': ConfigChange.query.count(),
            'today_configs': ConfigChange.query.filter(ConfigChange.change_time >= today_start).count(),
            'ticket_count': DesktopTicket.query.count(),
            'pending_tickets': DesktopTicket.query.filter(
                DesktopTicket.status.in_(['待处理', '处理中'])
            ).count(),
            'resolution_rate': 0,
            'avg_resolution_hours': 0,
        }

        # 解决率
        resolved = DesktopTicket.query.filter(DesktopTicket.status.in_(['已解决', '已关闭'])).count()
        if stats['ticket_count'] > 0:
            stats['resolution_rate'] = round(resolved / stats['ticket_count'] * 100, 1)

        # 平均解决时长
        closed_tickets = DesktopTicket.query.filter(
            DesktopTicket.status.in_(['已解决', '已关闭']),
            DesktopTicket.close_time.isnot(None)
        ).all()
        if closed_tickets:
            total_hours = sum((t.close_time - t.create_time).total_seconds() / 3600 for t in closed_tickets)
            stats['avg_resolution_hours'] = total_hours / len(closed_tickets)

        # 图表数据
        attack_severity_labels = AttackEvent.SEVERITY_LIST
        attack_severity_data = [
            AttackEvent.query.filter(AttackEvent.severity == s).count()
            for s in attack_severity_labels
        ]

        ticket_status_labels = DesktopTicket.STATUS_LIST
        ticket_status_data = [
            DesktopTicket.query.filter(DesktopTicket.status == s).count()
            for s in ticket_status_labels
        ]

        config_type_labels = ConfigChange.CONFIG_TYPE_LIST
        config_type_data = [
            ConfigChange.query.filter(ConfigChange.config_type == t).count()
            for t in config_type_labels
        ]

        # 趋势数据
        trend_labels = []
        trend_attack_data = []
        trend_config_data = []
        trend_ticket_data = []
        for i in range(6, -1, -1):
            day = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day + timedelta(days=1)
            trend_labels.append(day.strftime('%m-%d'))
            trend_attack_data.append(AttackEvent.query.filter(
                AttackEvent.attack_time >= day, AttackEvent.attack_time < day_end
            ).count())
            trend_config_data.append(ConfigChange.query.filter(
                ConfigChange.change_time >= day, ConfigChange.change_time < day_end
            ).count())
            trend_ticket_data.append(DesktopTicket.query.filter(
                DesktopTicket.create_time >= day, DesktopTicket.create_time < day_end
            ).count())

        # 最近记录
        recent_attacks = AttackEvent.query.order_by(AttackEvent.attack_time.desc()).limit(6).all()
        recent_configs = ConfigChange.query.order_by(ConfigChange.change_time.desc()).limit(6).all()
        recent_tickets = DesktopTicket.query.order_by(DesktopTicket.create_time.desc()).limit(6).all()

        return {
            'stats': stats,
            'now': now,
            'attack_severity_labels': attack_severity_labels,
            'attack_severity_data': attack_severity_data,
            'ticket_status_labels': ticket_status_labels,
            'ticket_status_data': ticket_status_data,
            'config_type_labels': config_type_labels,
            'config_type_data': config_type_data,
            'trend_labels': trend_labels,
            'trend_attack_data': trend_attack_data,
            'trend_config_data': trend_config_data,
            'trend_ticket_data': trend_ticket_data,
            'recent_attacks': recent_attacks,
            'recent_configs': recent_configs,
            'recent_tickets': recent_tickets,
        }

    @staticmethod
    def get_quick_links():
        """快速访问链接"""
        return QuickLink.query.order_by(QuickLink.sort_order.asc(), QuickLink.created_at.desc()).all()