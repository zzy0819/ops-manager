"""结构化日志配置"""
import json
import logging
from datetime import datetime
from flask import request, g
import time


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        if hasattr(record, 'request_id'):
            log_data['request_id'] = record.request_id
        if hasattr(record, 'user'):
            log_data['user'] = record.user
        if hasattr(record, 'duration'):
            log_data['duration_ms'] = record.duration
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(app):
    """配置应用日志"""
    # 移除默认处理器
    for handler in app.logger.handlers[:]:
        app.logger.removeHandler(handler)

    # 控制台输出（开发环境）
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(JSONFormatter())
    console_handler.setLevel(logging.INFO)

    # 文件输出（生产环境）
    file_handler = logging.FileHandler('logs/app.log', encoding='utf-8')
    file_handler.setFormatter(JSONFormatter())
    file_handler.setLevel(logging.WARNING)

    app.logger.addHandler(console_handler)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)

    # 禁用 Werkzeug 默认日志
    logging.getLogger('werkzeug').setLevel(logging.WARNING)


def log_request_info():
    """记录请求信息到日志上下文"""
    g.start_time = time.time()
    g.request_id = datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]


def log_response_info(response):
    """记录响应信息"""
    if hasattr(g, 'start_time'):
        duration = (time.time() - g.start_time) * 1000
        extra = {
            'request_id': getattr(g, 'request_id', 'unknown'),
            'method': request.method,
            'path': request.path,
            'status': response.status_code,
            'duration': f'{duration:.2f}ms',
            'user_agent': request.user_agent.string[:100] if request.user_agent else '',
            'ip': request.remote_addr,
        }
        app.logger.info('Request completed', extra=extra)
    return response