"""IP扫描路由（委托到服务层）"""
import os
import threading
import ipaddress
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify, abort
from app.extensions import db
from app.models import IPScanResult
from app.services.ip_scan_service import IPScanService

ip_scan_bp = Blueprint('ip_scan', __name__, url_prefix='/ip-scan')

MAX_SUBNET_SIZE = 1024


@ip_scan_bp.route('/scan-progress/<int:scan_id>')
def scan_progress(scan_id):
    """AJAX 轮询接口：返回扫描进度。"""
    scan = db.session.get(IPScanResult, scan_id)
    if not scan:
        abort(404)
    if scan.result_file:
        base_dir = current_app.config.get('BASE_DIR')
        result_content, alive_hosts = IPScanService.read_result_file(base_dir, scan.result_file)
        hosts = list(ipaddress.ip_network(scan.subnet, strict=False).hosts())
        all_ips = [str(ip) for ip in hosts]
        return jsonify({
            'scanned': scan.total_ips, 'total': scan.total_ips,
            'alive': scan.alive_ips,
            'alive_hosts': alive_hosts,
            'all_ips': all_ips,
            'status': 'done',
            'duration': scan.scan_duration,
        })

    progress = IPScanService.get_progress(scan_id)
    if not progress:
        progress = {'scanned': 0, 'total': scan.total_ips, 'alive': 0, 'alive_hosts': [], 'status': 'scanning'}
    hosts = list(ipaddress.ip_network(scan.subnet, strict=False).hosts())
    all_ips = [str(ip) for ip in hosts]
    return jsonify({
        **progress,
        'all_ips': all_ips,
    })


@ip_scan_bp.route('/', methods=['GET', 'POST'])
def ip_scan():
    if request.method == 'POST':
        subnet = request.form.get('subnet', '').strip()
        if not subnet:
            flash('请输入要扫描的网段', 'danger')
            return redirect(url_for('ip_scan.ip_scan'))

        try:
            network = ipaddress.ip_network(subnet, strict=False)
            total_ips = network.num_addresses

            if total_ips > MAX_SUBNET_SIZE:
                flash(f'网段过大 ({total_ips} 个IP)，请指定更小的子网（如 /24）', 'warning')
                return redirect(url_for('ip_scan.ip_scan'))

            scan = IPScanService.create_scan_record(subnet, total_ips)
            scan_id = scan.id
            db.session.expunge(scan)

            app = current_app._get_current_object()
            base_dir = current_app.config.get('BASE_DIR')

            IPScanService.start_scan_async(subnet, scan_id, base_dir, app)

            flash(f'已开始扫描网段 {subnet}，实时进度见下方', 'success')
            return redirect(url_for('ip_scan.ip_scan_results', scan_id=scan_id))

        except ValueError as e:
            flash(f'网段格式错误: {str(e)}', 'danger')

    history = IPScanService.get_recent_scans(10)
    return render_template('ipscan.html', history=history)


@ip_scan_bp.route('/results/<int:scan_id>')
def ip_scan_results(scan_id):
    scan = db.session.get(IPScanResult, scan_id)
    if not scan:
        abort(404)
    base_dir = current_app.config.get('BASE_DIR')

    result_content, alive_hosts = IPScanService.read_result_file(base_dir, scan.result_file)

    all_ips = []
    try:
        network = ipaddress.ip_network(scan.subnet, strict=False)
        all_ips = [str(ip) for ip in network.hosts()]
    except Exception:
        pass

    return render_template('ipscan_results.html',
                           scan=scan,
                           result_content=result_content,
                           alive_hosts=alive_hosts,
                           all_ips=all_ips)


@ip_scan_bp.route('/delete/<int:scan_id>', methods=['POST'])
def ip_scan_delete(scan_id):
    scan = db.session.get(IPScanResult, scan_id)
    if not scan:
        abort(404)

    IPScanService.delete_scan(scan)
    flash('扫描记录已删除', 'success')
    return redirect(url_for('ip_scan.ip_scan'))