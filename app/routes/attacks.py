"""攻击事件路由（使用服务层）"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from app.models import AttackEvent
from app.services import AttackService

attacks_bp = Blueprint('attacks', __name__, url_prefix='/attacks')


@attacks_bp.route('/')
def attack_list():
    page = request.args.get('page', 1, type=int)
    attacks = AttackService.list_attacks(
        page=page,
        severity=request.args.get('severity', ''),
        status=request.args.get('status', ''),
        keyword=request.args.get('keyword', '')
    )
    return render_template('attacks.html', attacks=attacks,
                           severity=request.args.get('severity', ''),
                           status=request.args.get('status', ''),
                           keyword=request.args.get('keyword', ''),
                           severity_list=AttackEvent.SEVERITY_LIST,
                           status_list=AttackEvent.STATUS_LIST)


@attacks_bp.route('/new', methods=['GET', 'POST'])
def attack_create():
    if request.method == 'POST':
        AttackService.create(request.form)
        flash('攻击事件记录已创建', 'success')
        return redirect(url_for('attacks.attack_list'))
    return render_template('attack_form.html', attack=None,
                           type_list=AttackEvent.TYPE_LIST,
                           severity_list=AttackEvent.SEVERITY_LIST,
                           status_list=AttackEvent.STATUS_LIST)


@attacks_bp.route('/<int:attack_id>/edit', methods=['GET', 'POST'])
def attack_edit(attack_id):
    attack = AttackService.get_by_id(attack_id)
    if not attack:
        abort(404)
    if request.method == 'POST':
        AttackService.update(attack, request.form)
        flash('攻击事件记录已更新', 'success')
        return redirect(url_for('attacks.attack_list'))
    return render_template('attack_form.html', attack=attack,
                           type_list=AttackEvent.TYPE_LIST,
                           severity_list=AttackEvent.SEVERITY_LIST,
                           status_list=AttackEvent.STATUS_LIST)


@attacks_bp.route('/<int:attack_id>/delete', methods=['POST'])
def attack_delete(attack_id):
    attack = AttackService.get_by_id(attack_id)
    if not attack:
        abort(404)
    AttackService.delete(attack)
    flash('攻击事件记录已删除', 'success')
    return redirect(url_for('attacks.attack_list'))