import os
from flask import Flask
from app.config import Config
from app.extensions import db
from app.routes import register_blueprints


def create_app(config_overrides=None):
    app = Flask(__name__,
                template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates'))
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    app.config['BASE_DIR'] = os.path.dirname(os.path.dirname(__file__))

    # 群晖会话存储按应用配置初始化
    from app.services.synology_service import nas_session_store
    nas_session_store.configure(
        ttl=app.config.get('NAS_SESSION_TTL', 1800),
        max_sessions=app.config.get('NAS_MAX_SESSIONS', 100),
    )

    db.init_app(app)

    register_blueprints(app)

    with app.app_context():
        db.create_all()
        # 初始化默认系统链接
        from app.models import QuickLink
        if QuickLink.query.count() == 0:
            default_links = [
                QuickLink(name='东贝防火墙', url='https://10.12.10.250/', description='企业防火墙管理界面', sort_order=1),
                QuickLink(name='东贝NAC', url='https://10.12.10.251/', description='网络准入控制系统', sort_order=2),
                QuickLink(name='东贝AC', url='https://10.12.10.100/', description='无线控制器管理', sort_order=3),
                QuickLink(name='攻击事件管理', url='/attacks', description='网络安全攻击记录', sort_order=4),
                QuickLink(name='配置变更管理', url='/configs', description='网络配置变更记录', sort_order=5),
                QuickLink(name='工单管理', url='/tickets', description='桌面运维工单系统', sort_order=6),
                QuickLink(name='中控大屏', url='/dashboard', description='运维数据可视化大屏', sort_order=7),
                QuickLink(name='IP扫描', url='/ip-scan', description='内网IP存活扫描', sort_order=8),
            ]
            db.session.add_all(default_links)
            db.session.commit()
            print('已初始化默认系统链接')

    return app