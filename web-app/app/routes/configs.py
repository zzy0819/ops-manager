"""配置变更路由（使用服务层）"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from app.models import ConfigChange
from app.services import ConfigService

configs_bp = Blueprint('configs', __name__, url_prefix='/configs')


@configs_bp.route('/')
def config_list():
    page = request.args.get('page', 1, type=int)
    configs = ConfigService.list_configs(
        page=page,
        status=request.args.get('status', ''),
        config_type=request.args.get('config_type', ''),
        keyword=request.args.get('keyword', '')
    )
    return render_template('configs.html', configs=configs,
                           status=request.args.get('status', ''),
                           config_type=request.args.get('config_type', ''),
                           keyword=request.args.get('keyword', ''),
                           config_type_list=ConfigChange.CONFIG_TYPE_LIST,
                           status_list=ConfigChange.STATUS_LIST)


@configs_bp.route('/new', methods=['GET', 'POST'])
def config_create():
    if request.method == 'POST':
        ConfigService.create(request.form)
        flash('配置变更记录已创建', 'success')
        return redirect(url_for('configs.config_list'))
    return render_template('config_form.html', config=None,
                           config_type_list=ConfigChange.CONFIG_TYPE_LIST,
                           status_list=ConfigChange.STATUS_LIST)


@configs_bp.route('/<int:config_id>/edit', methods=['GET', 'POST'])
def config_edit(config_id):
    config = ConfigService.get_by_id(config_id)
    if not config:
        abort(404)
    if request.method == 'POST':
        ConfigService.update(config, request.form)
        flash('配置变更记录已更新', 'success')
        return redirect(url_for('configs.config_list'))
    return render_template('config_form.html', config=config,
                           config_type_list=ConfigChange.CONFIG_TYPE_LIST,
                           status_list=ConfigChange.STATUS_LIST)


@configs_bp.route('/<int:config_id>/delete', methods=['POST'])
def config_delete(config_id):
    config = ConfigService.get_by_id(config_id)
    if not config:
        abort(404)
    ConfigService.delete(config)
    flash('配置变更记录已删除', 'success')
    return redirect(url_for('configs.config_list'))