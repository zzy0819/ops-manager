import os
import sys

# 获取持久化数据目录：exe 运行时用 exe 所在目录，开发环境用项目根目录
if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.dirname(sys.executable)
else:
    DATA_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-2026-ops-manager'
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{os.path.join(DATA_DIR, "ops.db")}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
    }

    # 浏览器会话 Cookie（不要在其中保存 NAS 密码/SID）
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = _env_bool('SESSION_COOKIE_SECURE', False)

    # 群晖用户管理模块
    # 会话只存在进程内存，超时后需要重新登录 NAS
    NAS_SESSION_TTL = _env_int('NAS_SESSION_TTL', 1800)
    NAS_MAX_SESSIONS = _env_int('NAS_MAX_SESSIONS', 100)
    # 单次批量改密的用户数上限，避免一个 HTTP 请求长时间占用
    NAS_MAX_BATCH = _env_int('NAS_MAX_BATCH', 500)
    # 可选：逗号分隔的主机白名单。留空表示不限制。
    # 例：NAS_ALLOWED_HOSTS=nas1.corp.local,.corp.local,192.168.1.10
    NAS_ALLOWED_HOSTS = [
        item.strip()
        for item in os.environ.get('NAS_ALLOWED_HOSTS', '').split(',')
        if item.strip()
    ]
    # 关闭 TLS 校验时给出显式提示；默认仍然校验证书
    NAS_DEFAULT_VERIFY_SSL = _env_bool('NAS_DEFAULT_VERIFY_SSL', True)
