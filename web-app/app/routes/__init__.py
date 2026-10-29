def register_blueprints(app):
    from app.routes.main import main_bp
    from app.routes.attacks import attacks_bp
    from app.routes.configs import configs_bp
    from app.routes.tickets import tickets_bp
    from app.routes.devices import devices_bp
    from app.routes.ip_scan import ip_scan_bp
    from app.routes.reports import reports_bp
    from app.routes.quick_access import quick_access_bp
    from app.routes.security import security_bp
    from app.routes.monitor import monitor_bp
    from app.routes.config_backup import config_backup_bp
    from app.routes.diagnosis import diagnosis_bp
    from app.routes.nas_users import nas_users_bp
    from app.api.docs import docs_bp
    from app.api.v1.attacks import api_attacks_bp
    from app.api.v1.configs import api_configs_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(attacks_bp)
    app.register_blueprint(configs_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(ip_scan_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(quick_access_bp)
    app.register_blueprint(security_bp)
    app.register_blueprint(monitor_bp)
    app.register_blueprint(config_backup_bp)
    app.register_blueprint(diagnosis_bp)
    app.register_blueprint(nas_users_bp)
    app.register_blueprint(docs_bp)

    # API v1 端点
    app.register_blueprint(api_attacks_bp, url_prefix='/api/v1/attacks')
    app.register_blueprint(api_configs_bp, url_prefix='/api/v1/configs')