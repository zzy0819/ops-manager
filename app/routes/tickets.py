"""运维工单路由（使用服务层）"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from app.models import DesktopTicket
from app.services import TicketService

tickets_bp = Blueprint('tickets', __name__, url_prefix='/tickets')


@tickets_bp.route('/')
def ticket_list():
    page = request.args.get('page', 1, type=int)
    tickets = TicketService.list_tickets(
        page=page,
        status=request.args.get('status', ''),
        priority=request.args.get('priority', ''),
        keyword=request.args.get('keyword', '')
    )
    return render_template('tickets.html', tickets=tickets,
                           status=request.args.get('status', ''),
                           priority=request.args.get('priority', ''),
                           problem_type=request.args.get('problem_type', ''),
                           keyword=request.args.get('keyword', ''),
                           problem_type_list=DesktopTicket.PROBLEM_TYPE_LIST,
                           priority_list=DesktopTicket.PRIORITY_LIST,
                           status_list=DesktopTicket.STATUS_LIST)


@tickets_bp.route('/new', methods=['GET', 'POST'])
def ticket_create():
    if request.method == 'POST':
        TicketService.create(request.form)
        flash('工单已创建', 'success')
        return redirect(url_for('tickets.ticket_list'))
    return render_template('ticket_form.html', ticket=None,
                           problem_type_list=DesktopTicket.PROBLEM_TYPE_LIST,
                           priority_list=DesktopTicket.PRIORITY_LIST,
                           status_list=DesktopTicket.STATUS_LIST)


@tickets_bp.route('/<int:ticket_id>/edit', methods=['GET', 'POST'])
def ticket_edit(ticket_id):
    ticket = TicketService.get_by_id(ticket_id)
    if not ticket:
        abort(404)
    if request.method == 'POST':
        TicketService.update(ticket, request.form)
        flash('工单已更新', 'success')
        return redirect(url_for('tickets.ticket_list'))
    return render_template('ticket_form.html', ticket=ticket,
                           problem_type_list=DesktopTicket.PROBLEM_TYPE_LIST,
                           priority_list=DesktopTicket.PRIORITY_LIST,
                           status_list=DesktopTicket.STATUS_LIST)


@tickets_bp.route('/<int:ticket_id>/delete', methods=['POST'])
def ticket_delete(ticket_id):
    ticket = TicketService.get_by_id(ticket_id)
    if not ticket:
        abort(404)
    TicketService.delete(ticket)
    flash('工单已删除', 'success')
    return redirect(url_for('tickets.ticket_list'))