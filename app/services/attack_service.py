"""攻击事件服务层"""
from datetime import datetime
from app.extensions import db
from app.models import AttackEvent


class AttackService:
    """攻击事件业务逻辑"""

    @staticmethod
    def list_attacks(page=1, per_page=15, severity='', status='', keyword=''):
        query = AttackEvent.query
        if severity:
            query = query.filter(AttackEvent.severity == severity)
        if status:
            query = query.filter(AttackEvent.status == status)
        if keyword:
            query = query.filter(
                db.or_(
                    AttackEvent.source_ip.contains(keyword),
                    AttackEvent.target_ip.contains(keyword),
                    AttackEvent.description.contains(keyword),
                    AttackEvent.handler.contains(keyword)
                )
            )
        return query.order_by(AttackEvent.attack_time.desc()).paginate(
            page=page, per_page=per_page, error_out=False)

    @staticmethod
    def get_by_id(attack_id):
        return db.session.get(AttackEvent, attack_id)

    @staticmethod
    def create(data: dict):
        attack = AttackEvent(
            attack_time=datetime.strptime(data['attack_time'], '%Y-%m-%dT%H:%M'),
            attack_type=data['attack_type'],
            source_ip=data['source_ip'],
            target_ip=data['target_ip'],
            target_port=int(data['target_port']) if data.get('target_port') else None,
            severity=data['severity'],
            description=data.get('description', ''),
            handler=data.get('handler', ''),
            status=data['status']
        )
        db.session.add(attack)
        db.session.commit()
        return attack

    @staticmethod
    def update(attack, data: dict):
        attack.attack_time = datetime.strptime(data['attack_time'], '%Y-%m-%dT%H:%M')
        attack.attack_type = data['attack_type']
        attack.source_ip = data['source_ip']
        attack.target_ip = data['target_ip']
        attack.target_port = int(data['target_port']) if data.get('target_port') else None
        attack.severity = data['severity']
        attack.description = data.get('description', '')
        attack.handler = data.get('handler', '')
        attack.status = data['status']
        db.session.commit()
        return attack

    @staticmethod
    def delete(attack):
        db.session.delete(attack)
        db.session.commit()
