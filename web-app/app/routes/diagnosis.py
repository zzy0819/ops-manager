"""网络连通性诊断路由蓝图

提供诊断主页面及 AJAX 接口，委托 DiagnosisService 处理业务逻辑。
"""

from flask import Blueprint, render_template, request, jsonify
from app.services.diagnosis_service import DiagnosisService, _is_valid_host, _is_valid_port

diagnosis_bp = Blueprint('diagnosis', __name__, url_prefix='/diagnosis')


@diagnosis_bp.route('/')
def diagnosis_page():
    """诊断主页面。"""
    return render_template('diagnosis.html')


@diagnosis_bp.route('/ping', methods=['POST'])
def ping():
    """Ping 诊断接口（JSON）。

    请求体 JSON:
        host: 目标 IP 或域名
        count: 发包数量（可选，默认 4）
    """
    data = request.get_json(silent=True) or {}
    host = data.get('host', '').strip()
    count = data.get('count', 4)

    if not host:
        return jsonify({'success': False, 'error': '请输入目标地址'}), 400

    try:
        count = int(count)
    except (ValueError, TypeError):
        count = 4

    result = DiagnosisService.ping(host, count=count)
    if not result.get('success'):
        return jsonify(result), 400
    return jsonify(result)


@diagnosis_bp.route('/traceroute', methods=['POST'])
def traceroute():
    """Traceroute 路由追踪接口（JSON）。

    请求体 JSON:
        host: 目标 IP 或域名
    """
    data = request.get_json(silent=True) or {}
    host = data.get('host', '').strip()

    if not host:
        return jsonify({'success': False, 'error': '请输入目标地址'}), 400

    result = DiagnosisService.traceroute(host)
    if not result.get('success'):
        return jsonify(result), 400
    return jsonify(result)


@diagnosis_bp.route('/port_scan', methods=['POST'])
def port_scan():
    """TCP 端口探测接口（JSON）。

    请求体 JSON:
        host: 目标 IP 或域名
        ports: 端口列表（逗号分隔的字符串或整数列表）
    """
    data = request.get_json(silent=True) or {}
    host = data.get('host', '').strip()
    ports_raw = data.get('ports', '')

    if not host:
        return jsonify({'success': False, 'error': '请输入目标地址'}), 400

    # 解析端口
    ports = []
    if isinstance(ports_raw, str):
        for p in ports_raw.split(','):
            p = p.strip()
            if p and _is_valid_port(p):
                ports.append(int(p))
    elif isinstance(ports_raw, list):
        for p in ports_raw:
            p_str = str(p).strip()
            if p_str and _is_valid_port(p_str):
                ports.append(int(p_str))

    if not ports:
        return jsonify({'success': False, 'error': '请输入有效的端口号'}), 400

    result = DiagnosisService.port_scan(host, ports)
    if not result.get('success'):
        return jsonify(result), 400
    return jsonify(result)


@diagnosis_bp.route('/dns', methods=['POST'])
def dns_resolve():
    """DNS 解析接口（JSON）。

    请求体 JSON:
        domain: 待解析域名
        dns_server: 指定 DNS 服务器（可选）
    """
    data = request.get_json(silent=True) or {}
    domain = data.get('domain', '').strip()
    dns_server = data.get('dns_server', '').strip() or None

    if not domain:
        return jsonify({'success': False, 'error': '请输入域名'}), 400

    result = DiagnosisService.dns_resolve(domain, dns_server=dns_server)
    if not result.get('success'):
        return jsonify(result), 400
    return jsonify(result)


@diagnosis_bp.route('/full', methods=['POST'])
def full_diagnosis():
    """一键诊断接口（JSON）。

    请求体 JSON:
        target: 目标 IP 或域名
    """
    data = request.get_json(silent=True) or {}
    target = data.get('target', '').strip()

    if not target:
        return jsonify({'success': False, 'error': '请输入目标地址'}), 400

    result = DiagnosisService.full_diagnosis(target)
    if not result.get('success'):
        return jsonify(result), 400
    return jsonify(result)
