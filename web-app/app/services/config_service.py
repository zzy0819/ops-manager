"""配置变更服务层"""
from datetime import datetime
from app.extensions import db
from app.models import ConfigChange


class ConfigService:
    """配置变更业务逻辑"""

    @staticmethod
    def list_configs(page=1, per_page=15, status='', config_type='', keyword=''):
        query = ConfigChange.query
        if status:
            query = query.filter(ConfigChange.change_status == status)
        if config_type:
            query = query.filter(ConfigChange.config_type == config_type)
        if keyword:
            query = query.filter(
                db.or_(
                    ConfigChange.device_name.contains(keyword),
                    ConfigChange.device_ip.contains(keyword),
                    ConfigChange.change_content.contains(keyword),
                    ConfigChange.operator.contains(keyword)
                )
            )
        return query.order_by(ConfigChange.change_time.desc()).paginate(
            page=page, per_page=per_page, error_out=False)

    @staticmethod
    def get_by_id(config_id):
        return db.session.get(ConfigChange, config_id)

    @staticmethod
    def create(data: dict):
        config = ConfigChange(
            change_time=datetime.strptime(data['change_time'], '%Y-%m-%dT%H:%M'),
            device_name=data['device_name'],
            device_ip=data['device_ip'],
            config_type=data['config_type'],
            change_content=data['change_content'],
            change_reason=data.get('change_reason', ''),
            operator=data['operator'],
            is_rollback=bool(data.get('is_rollback', False)),
            change_status=data['change_status']
        )
        db.session.add(config)
        db.session.commit()
        return config

    @staticmethod
    def update(config, data: dict):
        config.change_time = datetime.strptime(data['change_time'], '%Y-%m-%dT%H:%M')
        config.device_name = data['device_name']
        config.device_ip = data['device_ip']
        config.config_type = data['config_type']
        config.change_content = data['change_content']
        config.change_reason = data.get('change_reason', '')
        config.operator = data['operator']
        config.is_rollback = bool(data.get('is_rollback', False))
        config.change_status = data['change_status']
        db.session.commit()
        return config

    @staticmethod
    def delete(config):
        db.session.delete(config)
        db.session.commit()
