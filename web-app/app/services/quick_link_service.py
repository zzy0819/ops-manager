"""快速访问服务层"""
from app.extensions import db
from app.models import QuickLink


class QuickLinkService:
    """快速访问业务逻辑"""

    @staticmethod
    def list_links():
        """获取所有链接"""
        return QuickLink.query.order_by(QuickLink.sort_order.asc(), QuickLink.created_at.desc()).all()

    @staticmethod
    def get_by_id(link_id):
        """根据ID获取链接"""
        return db.session.get(QuickLink, link_id)

    @staticmethod
    def create(data):
        """创建链接"""
        link = QuickLink(
            name=data['name'],
            url=data['url'],
            description=data.get('description', ''),
            username=data.get('username', '') or None,
            password=data.get('password', '') or None,
            sort_order=int(data.get('sort_order', 0) or 0)
        )
        db.session.add(link)
        db.session.commit()
        return link

    @staticmethod
    def update(link, data):
        """更新链接"""
        link.name = data['name']
        link.url = data['url']
        link.description = data.get('description', '')
        link.username = data.get('username', '') or None
        link.password = data.get('password', '') or None
        link.sort_order = int(data.get('sort_order', 0) or 0)
        db.session.commit()
        return link

    @staticmethod
    def delete(link):
        """删除链接"""
        db.session.delete(link)
        db.session.commit()