"""API v1 配置变更接口"""
from flask import Blueprint, request, jsonify
from app.services import ConfigService

api_configs_bp = Blueprint('api_configs', __name__)


@api_configs_bp.route('/', methods=['GET'])
def list_configs():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = ConfigService.list_configs(page=page, per_page=per_page,
                                             change_status=request.args.get('status', ''),
                                             config_type=request.args.get('config_type', ''),
                                             keyword=request.args.get('keyword', ''))
    return jsonify({
        'code': 200,
        'data': {
            'items': [c.to_dict() for c in pagination.items],
            'total': pagination.total,
            'page': pagination.page,
            'pages': pagination.pages,
            'per_page': pagination.per_page
        }
    })


@api_configs_bp.route('/<int:config_id>', methods=['GET'])
def get_config(config_id):
    c = ConfigService.get_by_id(config_id)
    if not c:
        return jsonify({'code': 404, 'message': '配置变更不存在'}), 404
    return jsonify({'code': 200, 'data': c.to_dict()})


@api_configs_bp.route('/', methods=['POST'])
def create_config():
    c = ConfigService.create(request.json)
    return jsonify({'code': 201, 'data': c.to_dict()}), 201


@api_configs_bp.route('/<int:config_id>', methods=['PUT'])
def update_config(config_id):
    c = ConfigService.get_by_id(config_id)
    if not c:
        return jsonify({'code': 404, 'message': '配置变更不存在'}), 404
    c = ConfigService.update(c, request.json)
    return jsonify({'code': 200, 'data': c.to_dict()})


@api_configs_bp.route('/<int:config_id>', methods=['DELETE'])
def delete_config(config_id):
    c = ConfigService.get_by_id(config_id)
    if not c:
        return jsonify({'code': 404, 'message': '配置变更不存在'}), 404
    ConfigService.delete(c)
    return jsonify({'code': 200, 'message': '删除成功'})