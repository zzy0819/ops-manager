"""IP扫描服务层（完整版：含扫描编排、进度管理、结果存储）"""
import os
import subprocess
import threading
import ipaddress
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import current_app
from app.extensions import db
from app.models import IPScanResult

SCAN_WORKERS = 200
PING_TIMEOUT_MS = 300
MAX_SUBNET_SIZE = 1024

# 内存中存储扫描进度 (scan_id -> dict)
_scan_progress = {}


def _ping_one(ip_str):
    try:
        result = subprocess.run(
            ['ping', '-n', '1', '-w', str(PING_TIMEOUT_MS), ip_str],
            capture_output=True, text=True,
            timeout=(PING_TIMEOUT_MS / 1000.0) + 0.5,
        )
        alive = ('TTL=' in result.stdout or 'TTL =' in result.stdout)
        return (ip_str, alive)
    except Exception:
        return (ip_str, False)


class IPScanService:
    """IP扫描业务逻辑"""

    @staticmethod
    def get_progress(scan_id):
        """获取扫描进度"""
        return _scan_progress.get(scan_id)

    @staticmethod
    def set_progress(scan_id, progress):
        """更新扫描进度"""
        _scan_progress[scan_id] = progress

    @staticmethod
    def get_scan_by_id(scan_id):
        """根据ID获取扫描记录"""
        return db.session.get(IPScanResult, scan_id)

    @staticmethod
    def get_recent_scans(limit=10):
        """获取最近扫描历史"""
        return IPScanResult.query.order_by(IPScanResult.scan_time.desc()).limit(limit).all()

    @staticmethod
    def get_paginated_scans(page=1, per_page=20):
        """分页获取所有扫描记录"""
        pagination = IPScanResult.query.order_by(IPScanResult.scan_time.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        return pagination

    @staticmethod
    def create_scan_record(subnet, total_ips):
        """创建扫描记录并返回"""
        scan = IPScanResult(subnet=subnet, total_ips=total_ips)
        db.session.add(scan)
        db.session.commit()
        return scan

    @staticmethod
    def run_scan(subnet, scan_id, base_dir, app):
        """在后台线程中执行扫描"""
        global _scan_progress
        try:
            network = ipaddress.ip_network(subnet, strict=False)
            total_ips = network.num_addresses

            result_file = f'ipscan_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
            result_dir = os.path.join(base_dir, 'scans')
            result_path = os.path.join(result_dir, result_file)
            os.makedirs(result_dir, exist_ok=True)

            start_time = datetime.now()
            hosts = [str(ip) for ip in network.hosts()]

            _scan_progress[scan_id] = {
                'scanned': 0, 'total': len(hosts),
                'alive': 0, 'alive_hosts': [], 'status': 'scanning'
            }

            alive_list = []
            scanned_count = 0
            with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as executor:
                futures = {executor.submit(_ping_one, ip): ip for ip in hosts}
                for future in as_completed(futures):
                    ip, alive = future.result()
                    scanned_count += 1
                    if alive:
                        alive_list.append(ip)
                    if scanned_count % 50 == 0 or scanned_count == len(hosts):
                        _scan_progress[scan_id] = {
                            'scanned': scanned_count, 'total': len(hosts),
                            'alive': len(alive_list),
                            'alive_hosts': sorted(alive_list, key=lambda x: [int(n) for n in x.split('.')]),
                            'status': 'scanning'
                        }

            alive_list.sort(key=lambda x: [int(n) for n in x.split('.')])

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            alive_ips = len(alive_list)

            # 写入结果文件
            with open(result_path, 'w', encoding='utf-8') as f:
                f.write(f'扫描网段: {subnet}\n')
                f.write(f'扫描时间: {start_time.strftime("%Y-%m-%d %H:%M:%S")}\n')
                f.write(f'扫描耗时: {duration:.2f} 秒\n')
                f.write(f'扫描模式: 多线程并发 ({SCAN_WORKERS} 线程 / 超时 {PING_TIMEOUT_MS}ms)\n')
                f.write(f'总IP数: {total_ips}\n')
                f.write(f'存活IP数: {alive_ips}\n')
                f.write('=' * 50 + '\n')
                for ip in alive_list:
                    f.write(f'{ip}\n')

            # 更新数据库
            with app.app_context():
                scan = db.session.get(IPScanResult, scan_id)
                if scan:
                    scan.alive_ips = alive_ips
                    scan.scan_duration = duration
                    scan.result_file = result_file
                    db.session.commit()

            _scan_progress[scan_id] = {
                'scanned': len(hosts), 'total': len(hosts),
                'alive': alive_ips, 'alive_hosts': alive_list,
                'status': 'done'
            }

        except Exception as e:
            _scan_progress[scan_id] = {'status': 'error', 'error': str(e)}

    @staticmethod
    def start_scan_async(subnet, scan_id, base_dir, app):
        """异步启动扫描线程"""
        thread = threading.Thread(
            target=IPScanService.run_scan,
            args=(subnet, scan_id, base_dir, app),
            daemon=True
        )
        thread.start()

    @staticmethod
    def read_result_file(base_dir, result_file):
        """读取结果文件并解析存活主机"""
        alive_hosts = []
        result_content = None
        if result_file:
            result_path = os.path.join(base_dir, 'scans', result_file)
            if os.path.exists(result_path):
                try:
                    with open(result_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    result_content = content
                    lines = content.strip().split('\n')
                    in_hosts = False
                    for line in lines:
                        if line.startswith('='):
                            in_hosts = True
                            continue
                        if in_hosts and line.strip():
                            alive_hosts.append(line.strip())
                except Exception:
                    result_content = '无法读取结果文件'
        return result_content, alive_hosts

    @staticmethod
    def delete_scan(scan):
        """删除扫描记录及结果文件"""
        base_dir = current_app.config.get('BASE_DIR')
        if scan.result_file:
            result_path = os.path.join(base_dir, 'scans', scan.result_file)
            if os.path.exists(result_path):
                try:
                    os.remove(result_path)
                except Exception:
                    pass
        db.session.delete(scan)
        db.session.commit()