"""API v1 __init__ - 注册API蓝图"""
from app.api.v1.attacks import api_attacks_bp
from app.api.v1.configs import api_configs_bp

__all__ = ['api_attacks_bp', 'api_configs_bp']