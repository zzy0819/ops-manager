"""运维工单服务层"""
from datetime import datetime
from app.extensions import db
from app.models import DesktopTicket


class TicketService:
    """运维工单业务逻辑"""

    @staticmethod
    def list_tickets(page=1, per_page=15, status='', priority='', keyword=''):
        query = DesktopTicket.query
        if status:
            query = query.filter(DesktopTicket.status == status)
        if priority:
            query = query.filter(DesktopTicket.priority == priority)
        if keyword:
            query = query.filter(
                db.or_(
                    DesktopTicket.ticket_number.contains(keyword),
                    DesktopTicket.requester.contains(keyword),
                    DesktopTicket.problem_description.contains(keyword),
                    DesktopTicket.assignee.contains(keyword)
                )
            )
        return query.order_by(DesktopTicket.create_time.desc()).paginate(
            page=page, per_page=per_page, error_out=False)

    @staticmethod
    def get_by_id(ticket_id):
        return db.session.get(DesktopTicket, ticket_id)

    @staticmethod
    def generate_ticket_number():
        today = datetime.now().strftime('%Y%m%d')
        count = DesktopTicket.query.filter(
            DesktopTicket.ticket_number.like(f'TK-{today}-%')
        ).count()
        return f'TK-{today}-{count + 1:03d}'

    @staticmethod
    def create(data: dict):
        ticket = DesktopTicket(
            ticket_number=TicketService.generate_ticket_number(),
            create_time=datetime.strptime(data['create_time'], '%Y-%m-%dT%H:%M'),
            requester=data['requester'],
            department=data['department'],
            contact=data['contact'],
            problem_type=data['problem_type'],
            problem_description=data['problem_description'],
            priority=data.get('priority', '中'),
            assignee=data.get('assignee', ''),
            status=data.get('status', '待处理'),
            solution=data.get('solution', '')
        )
        db.session.add(ticket)
        db.session.commit()
        return ticket

    @staticmethod
    def update(ticket, data: dict):
        ticket.create_time = datetime.strptime(data['create_time'], '%Y-%m-%dT%H:%M')
        ticket.requester = data['requester']
        ticket.department = data['department']
        ticket.contact = data['contact']
        ticket.problem_type = data['problem_type']
        ticket.problem_description = data['problem_description']
        ticket.priority = data.get('priority', '中')
        ticket.assignee = data.get('assignee', '')
        ticket.status = data.get('status', '待处理')
        ticket.solution = data.get('solution', '')
        if ticket.status in ('已解决', '已关闭') and not ticket.close_time:
            ticket.close_time = datetime.now()
        db.session.commit()
        return ticket

    @staticmethod
    def delete(ticket):
        db.session.delete(ticket)
        db.session.commit()
