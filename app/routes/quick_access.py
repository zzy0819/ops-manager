"""快速访问路由（委托到服务层）"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from app.services import QuickLinkService

quick_access_bp = Blueprint('quick_access', __name__, url_prefix='/quick')


@quick_access_bp.route('/')
def quick_access():
    links = QuickLinkService.list_links()
    return render_template('quick.html', quick_links=links)


@quick_access_bp.route('/new', methods=['GET', 'POST'])
def quick_create():
    if request.method == 'POST':
        link = QuickLinkService.create(request.form)
        flash(f'系统 "{link.name}" 已添加', 'success')
        return redirect(url_for('quick_access.quick_access'))
    return render_template('quick_form.html', link=None)


@quick_access_bp.route('/<int:link_id>/edit', methods=['GET', 'POST'])
def quick_edit(link_id):
    link = QuickLinkService.get_by_id(link_id)
    if not link:
        abort(404)
    if request.method == 'POST':
        QuickLinkService.update(link, request.form)
        flash(f'系统 "{link.name}" 已更新', 'success')
        return redirect(url_for('quick_access.quick_access'))
    return render_template('quick_form.html', link=link)


@quick_access_bp.route('/<int:link_id>/delete', methods=['POST'])
def quick_delete(link_id):
    link = QuickLinkService.get_by_id(link_id)
    if not link:
        abort(404)
    name = link.name
    QuickLinkService.delete(link)
    flash(f'系统 "{name}" 已删除', 'success')
    return redirect(url_for('quick_access.quick_access'))