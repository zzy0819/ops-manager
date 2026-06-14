"""API v1 攻击事件接口"""
from flask import Blueprint, request, jsonify
from app.services import AttackService

api_attacks_bp = Blueprint('api_attacks', __name__)


@api_attacks_bp.route('/', methods=['GET'])
def list_attacks():
    """获取攻击事件列表"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status = request.args.get('status', '')
    severity = request.args.get('severity', '')
    attack_type = request.args.get('attack_type', '')
    keyword = request.args.get('keyword', '')

    pagination = AttackService.list_attacks(
        page=page, per_page=per_page,
        status=status, severity=severity,
        attack_type=attack_type, keyword=keyword
    )

    return jsonify({
        'code': 200,
        'data': {
            'items': [a.to_dict() for a in pagination.items],
            'total': pagination.total,
            'page': pagination.page,
            'pages': pagination.pages,
            'per_page': pagination.per_page
        }
    })


@api_attacks_bp.route('/<int:attack_id>', methods=['GET'])
def get_attack(attack_id):
    """获取单个攻击事件"""
    attack = AttackService.get_by_id(attack_id)
    if not attack:
        return jsonify({'code': 404, 'message': '攻击事件不存在'}), 404
    return jsonify({'code': 200, 'data': attack.to_dict()})


@api_attacks_bp.route('/', methods=['POST'])
def create_attack():
    """创建攻击事件"""
    attack = AttackService.create(request.json)
    return jsonify({'code': 201, 'data': attack.to_dict(), 'message': '创建成功'}), 201


@api_attacks_bp.route('/<int:attack_id>', methods=['PUT'])
def update_attack(attack_id):
    """更新攻击事件"""
    attack = AttackService.get_by_id(attack_id)
    if not attack:
        return jsonify({'code': 404, 'message': '攻击事件不存在'}), 404
    attack = AttackService.update(attack, request.json)
    return jsonify({'code': 200, 'data': attack.to_dict(), 'message': '更新成功'})


@api_attacks_bp.route('/<int:attack_id>', methods=['DELETE'])
def delete_attack(attack_id):
    """删除攻击事件"""
    attack = AttackService.get_by_id(attack_id)
    if not attack:
        return jsonify({'code': 404, 'message': '攻击事件不存在'}), 404
    AttackService.delete(attack)
    return jsonify({'code': 200, 'message': '删除成功'})