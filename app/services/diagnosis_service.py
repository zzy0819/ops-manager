"""网络连通性诊断服务层

提供 ICMP Ping、Traceroute、TCP 端口探测、DNS 解析及一键诊断功能。
所有方法返回结构化 dict，方便路由层直接 JSON 化。
"""

import re
import socket
import subprocess
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 输入校验工具
# ---------------------------------------------------------------------------

_HOST_RE = re.compile(
    r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*'
    r'[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$'
)

_IP_RE = re.compile(
    r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$'
)


def _is_valid_host(host: str) -> bool:
    """校验主机地址是否为合法 IP 或域名，防止命令注入。

    Args:
        host: 用户输入的目标地址字符串。

    Returns:
        True 表示合法，False 表示非法。
    """
    if not host or len(host) > 253:
        return False
    # 先检查是否为合法 IP
    m = _IP_RE.match(host)
    if m:
        return all(0 <= int(octet) <= 255 for octet in m.groups())
    # 再检查是否为合法域名
    return bool(_HOST_RE.match(host))


def _is_valid_port(port_str: str) -> bool:
    """校验端口字符串是否为合法端口号（1-65535）。

    Args:
        port_str: 端口号字符串。

    Returns:
        True 表示合法，False 表示非法。
    """
    try:
        port = int(port_str)
        return 1 <= port <= 65535
    except (ValueError, TypeError):
        return False


# Windows 子进程公共标志
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]


def _run_subprocess(cmd: List[str], timeout: int, encoding: str = 'gbk') -> Tuple[str, str, int]:
    """执行子进程并返回 (stdout, stderr, returncode)。

    Args:
        cmd: 命令及参数列表。
        timeout: 超时秒数。
        encoding: 输出编码，Windows 下默认 gbk。

    Returns:
        (stdout, stderr, returncode) 三元组。
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            creationflags=_SUBPROCESS_FLAGS,
        )
        stdout = result.stdout.decode(encoding, errors='replace')
        stderr = result.stderr.decode(encoding, errors='replace')
        return stdout, stderr, result.returncode
    except subprocess.TimeoutExpired:
        return '', '命令执行超时', -1
    except Exception as exc:
        return '', str(exc), -1


# ---------------------------------------------------------------------------
# DiagnosisService
# ---------------------------------------------------------------------------

class DiagnosisService:
    """网络连通性诊断服务，封装所有诊断方法。"""

    # 常用端口列表
    COMMON_PORTS: List[int] = [22, 23, 80, 443, 3389, 8080]

    # ---- ICMP Ping ----

    @staticmethod
    def ping(host: str, count: int = 4) -> Dict:
        """执行 ICMP Ping 诊断。

        Args:
            host: 目标 IP 或域名。
            count: 发包数量，默认 4，最大 20。

        Returns:
            结构化诊断结果 dict。
        """
        if not _is_valid_host(host):
            return {'success': False, 'error': '目标地址格式不合法'}

        count = max(1, min(20, int(count)))

        cmd = ['ping', '-n', str(count), host]
        stdout, stderr, rc = _run_subprocess(cmd, timeout=count * 3 + 5)

        if rc == -1:
            return {'success': False, 'error': stderr or 'Ping 执行超时'}

        # 解析每个包的延迟
        details = []
        # Windows ping 输出：来自 10.12.10.1 的回复: 字节=32 时间=1ms TTL=64
        # 或：Reply from 10.12.10.1: bytes=32 time=1ms TTL=64
        reply_pattern = re.compile(
            r'(?:来自|Reply from)\s+\S+.*?时间[=<](\d+)ms|time[=<](\d+)ms',
            re.IGNORECASE
        )
        # 超时模式：请求超时 / Request timed out
        timeout_pattern = re.compile(r'(?:请求超时|Request timed out)', re.IGNORECASE)

        seq = 0
        for line in stdout.splitlines():
            seq += 1
            m = reply_pattern.search(line)
            if m:
                latency_str = m.group(1) or m.group(2)
                latency = float(latency_str) if latency_str else 0.0
                details.append({'seq': seq, 'time': latency, 'status': 'ok'})
            elif timeout_pattern.search(line):
                details.append({'seq': seq, 'time': None, 'status': 'timeout'})

        # 解析统计行
        # Windows: 丢包率 = 0% (0/4)
        loss_rate = 100.0
        min_lat, max_lat, avg_lat = None, None, None

        loss_match = re.search(r'\((\d+)%\s+丢失\)|Lost = \d+ \((\d+)%', stdout)
        if loss_match:
            loss_rate = float(loss_match.group(1) or loss_match.group(2))

        # Windows: 最短 = 1ms，最长 = 3ms，平均 = 2ms
        # 或: Minimum = 1ms, Maximum = 3ms, Average = 2ms
        stat_match = re.search(
            r'(?:最短|Minimum)\s*[=＝]\s*(\d+)ms.*?'
            r'(?:最长|Maximum)\s*[=＝]\s*(\d+)ms.*?'
            r'(?:平均|Average)\s*[=＝]\s*(\d+)ms',
            stdout, re.IGNORECASE | re.DOTALL
        )
        if stat_match:
            min_lat = float(stat_match.group(1))
            max_lat = float(stat_match.group(2))
            avg_lat = float(stat_match.group(3))

        packets_sent = count
        packets_received = len([d for d in details if d['status'] == 'ok'])

        # 如果没有解析到统计行，从 details 推算
        if packets_received > 0 and avg_lat is None:
            times = [d['time'] for d in details if d['status'] == 'ok' and d['time'] is not None]
            if times:
                min_lat = min(times)
                max_lat = max(times)
                avg_lat = round(sum(times) / len(times), 1)
                loss_rate = round((1 - len(times) / count) * 100, 1)

        return {
            'success': True,
            'host': host,
            'count': count,
            'packets_sent': packets_sent,
            'packets_received': packets_received,
            'loss_rate': loss_rate,
            'min_latency': min_lat,
            'max_latency': max_lat,
            'avg_latency': avg_lat,
            'details': details,
        }

    # ---- Traceroute ----

    @staticmethod
    def traceroute(host: str) -> Dict:
        """执行 Traceroute 路由追踪。

        Args:
            host: 目标 IP 或域名。

        Returns:
            结构化路由追踪结果 dict。
        """
        if not _is_valid_host(host):
            return {'success': False, 'error': '目标地址格式不合法'}

        # Windows: tracert -d 不解析域名，加速
        cmd = ['tracert', '-d', host]
        stdout, stderr, rc = _run_subprocess(cmd, timeout=60)

        if rc == -1 and not stdout:
            return {'success': False, 'error': stderr or 'Traceroute 执行超时'}

        hops = []
        # Windows tracert 输出：
        #   1    <1 ms    <1 ms    <1 ms  10.12.10.1
        #   2     *        *        *     请求超时。
        hop_pattern = re.compile(
            r'^\s*(\d+)\s+'
            r'(?:<(\d+)\s*ms|\*)\s+'
            r'(?:<(\d+)\s*ms|\*)\s+'
            r'(?:<(\d+)\s*ms|\*)\s+'
            r'(\S+)'
        )
        timeout_line_pattern = re.compile(
            r'^\s*(\d+)\s+\*\s+\*\s+\*\s+(?:请求超时|Request timed out)',
            re.IGNORECASE
        )

        for line in stdout.splitlines():
            m = hop_pattern.match(line)
            if m:
                hop_num = int(m.group(1))
                times = []
                for g in (m.group(2), m.group(3), m.group(4)):
                    if g is not None:
                        times.append(float(g))
                    else:
                        times.append(None)
                ip_addr = m.group(5)
                is_timeout = all(t is None for t in times)
                hops.append({
                    'hop': hop_num,
                    'ip': ip_addr if not is_timeout else '*',
                    'times': times,
                    'timeout': is_timeout,
                })
            else:
                m2 = timeout_line_pattern.match(line)
                if m2:
                    hops.append({
                        'hop': int(m2.group(1)),
                        'ip': '*',
                        'times': [None, None, None],
                        'timeout': True,
                    })

        return {
            'success': True,
            'host': host,
            'hops': hops,
            'total_hops': len(hops),
        }

    # ---- TCP 端口探测 ----

    @staticmethod
    def port_scan(host: str, ports: List[int]) -> Dict:
        """执行 TCP 端口探测。

        Args:
            host: 目标 IP 或域名。
            ports: 要探测的端口列表。

        Returns:
            结构化端口探测结果 dict。
        """
        if not _is_valid_host(host):
            return {'success': False, 'error': '目标地址格式不合法'}

        if not ports:
            return {'success': False, 'error': '未指定端口'}

        results = []
        for port in ports:
            if not (1 <= port <= 65535):
                results.append({
                    'port': port,
                    'status': 'invalid',
                    'response_time': None,
                    'error': '端口号超出范围',
                })
                continue

            start_time = time.time()
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect((host, port))
                elapsed = round((time.time() - start_time) * 1000, 1)
                sock.close()
                results.append({
                    'port': port,
                    'status': 'open',
                    'response_time': elapsed,
                    'error': None,
                })
            except socket.timeout:
                elapsed = round((time.time() - start_time) * 1000, 1)
                results.append({
                    'port': port,
                    'status': 'closed',
                    'response_time': elapsed,
                    'error': '连接超时',
                })
            except ConnectionRefusedError:
                elapsed = round((time.time() - start_time) * 1000, 1)
                results.append({
                    'port': port,
                    'status': 'closed',
                    'response_time': elapsed,
                    'error': '连接被拒绝',
                })
            except Exception as exc:
                elapsed = round((time.time() - start_time) * 1000, 1)
                results.append({
                    'port': port,
                    'status': 'error',
                    'response_time': elapsed,
                    'error': str(exc),
                })

        open_count = len([r for r in results if r['status'] == 'open'])

        return {
            'success': True,
            'host': host,
            'ports': results,
            'total': len(results),
            'open_count': open_count,
            'closed_count': len(results) - open_count,
        }

    # ---- DNS 解析 ----

    @staticmethod
    def dns_resolve(domain: str, dns_server: Optional[str] = None) -> Dict:
        """执行 DNS 解析。

        Args:
            domain: 待解析的域名。
            dns_server: 指定 DNS 服务器，None 则使用系统默认。

        Returns:
            结构化 DNS 解析结果 dict。
        """
        if not _is_valid_host(domain):
            return {'success': False, 'error': '域名格式不合法'}

        if dns_server and not _is_valid_host(dns_server):
            return {'success': False, 'error': 'DNS 服务器地址不合法'}

        start_time = time.time()
        ips: List[str] = []
        used_server = dns_server or '系统默认'

        if dns_server:
            # 使用 nslookup 指定 DNS 服务器
            cmd = ['nslookup', domain, dns_server]
            stdout, stderr, rc = _run_subprocess(cmd, timeout=10)
            if rc == -1:
                return {
                    'success': False,
                    'domain': domain,
                    'dns_server': dns_server,
                    'ips': [],
                    'elapsed': round((time.time() - start_time) * 1000, 1),
                    'error': stderr or 'nslookup 执行超时',
                }
            # 解析 nslookup 输出中的 IP
            # Windows: Addresses: 10.12.10.1
            # 或: Name: xxx  Address: 10.12.10.1
            ip_pattern = re.compile(r'Address(?:es)?:\s*((?:\d{1,3}\.){3}\d{1,3})')
            seen = set()
            for match in ip_pattern.finditer(stdout):
                ip_addr = match.group(1)
                if ip_addr not in seen:
                    ips.append(ip_addr)
                    seen.add(ip_addr)
        else:
            # 使用 socket.getaddrinfo
            try:
                addr_infos = socket.getaddrinfo(domain, None, socket.AF_INET)
                seen = set()
                for info in addr_infos:
                    ip_addr = info[4][0]
                    if ip_addr not in seen:
                        ips.append(ip_addr)
                        seen.add(ip_addr)
            except socket.gaierror as exc:
                elapsed = round((time.time() - start_time) * 1000, 1)
                return {
                    'success': False,
                    'domain': domain,
                    'dns_server': used_server,
                    'ips': [],
                    'elapsed': elapsed,
                    'error': f'DNS 解析失败: {str(exc)}',
                }
            except Exception as exc:
                elapsed = round((time.time() - start_time) * 1000, 1)
                return {
                    'success': False,
                    'domain': domain,
                    'dns_server': used_server,
                    'ips': [],
                    'elapsed': elapsed,
                    'error': f'DNS 解析异常: {str(exc)}',
                }

        elapsed = round((time.time() - start_time) * 1000, 1)

        return {
            'success': True,
            'domain': domain,
            'dns_server': used_server,
            'ips': ips,
            'elapsed': elapsed,
        }

    # ---- 一键诊断 ----

    @staticmethod
    def full_diagnosis(target: str) -> Dict:
        """执行一键诊断：Ping → Traceroute → 常用端口探测 → DNS 解析。

        Args:
            target: 目标 IP 或域名。

        Returns:
            完整诊断报告 dict，包含各项结果及摘要。
        """
        if not _is_valid_host(target):
            return {'success': False, 'error': '目标地址格式不合法'}

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 依次执行各项诊断
        ping_result = DiagnosisService.ping(target, count=4)
        traceroute_result = DiagnosisService.traceroute(target)
        port_result = DiagnosisService.port_scan(target, [22, 80, 443, 3389])
        dns_result = DiagnosisService.dns_resolve(target)

        # 生成摘要
        summary = DiagnosisService._generate_summary(
            target, ping_result, traceroute_result, port_result, dns_result
        )

        return {
            'success': True,
            'target': target,
            'timestamp': timestamp,
            'summary': summary,
            'ping': ping_result,
            'traceroute': traceroute_result,
            'port_scan': port_result,
            'dns': dns_result,
        }

    @staticmethod
    def _generate_summary(
        target: str,
        ping_result: Dict,
        traceroute_result: Dict,
        port_result: Dict,
        dns_result: Dict,
    ) -> Dict:
        """根据各项诊断结果生成故障摘要。

        故障层级判断逻辑：
        - DNS 解析失败 → 应用层问题
        - Ping 不可达但端口开放 → ICMP 被过滤
        - Ping 可达但端口不通 → 端口层/防火墙问题
        - Traceroute 中间断 → 路由问题
        - 全部正常 → 网络连通

        Args:
            target: 目标地址。
            ping_result: Ping 诊断结果。
            traceroute_result: Traceroute 结果。
            port_result: 端口探测结果。
            dns_result: DNS 解析结果。

        Returns:
            摘要 dict，包含 status / fault_layer / description。
        """
        dns_ok = dns_result.get('success', False) and len(dns_result.get('ips', [])) > 0
        ping_ok = (ping_result.get('success', False)
                   and ping_result.get('loss_rate', 100) < 100)
        port_open_count = port_result.get('open_count', 0) if port_result.get('success', False) else 0
        traceroute_ok = traceroute_result.get('success', False)

        # 检测 traceroute 是否中间断
        traceroute_broken = False
        if traceroute_ok:
            hops = traceroute_result.get('hops', [])
            if hops:
                # 如果最后几跳全是超时，说明路由中断
                last_valid_idx = -1
                for i in range(len(hops) - 1, -1, -1):
                    if not hops[i].get('timeout', False):
                        last_valid_idx = i
                        break
                # 如果最后3跳及以上连续超时
                consecutive_timeout = 0
                for hop in reversed(hops):
                    if hop.get('timeout', False):
                        consecutive_timeout += 1
                    else:
                        break
                if consecutive_timeout >= 3 and last_valid_idx < len(hops) - 1:
                    traceroute_broken = True

        # 判断逻辑
        if not dns_ok:
            return {
                'status': 'unreachable',
                'fault_layer': 'dns',
                'description': 'DNS 解析失败，可能为应用层/域名服务问题',
            }

        if not ping_ok and port_open_count > 0:
            return {
                'status': 'partial',
                'fault_layer': 'icmp_filtered',
                'description': 'ICMP 不可达但端口开放，目标可能过滤了 ICMP 包',
            }

        if traceroute_broken:
            return {
                'status': 'partial',
                'fault_layer': 'route',
                'description': '路由追踪中间中断，可能存在路由问题',
            }

        if ping_ok and port_open_count == 0:
            return {
                'status': 'partial',
                'fault_layer': 'port',
                'description': 'Ping 可达但常用端口均不通，可能存在端口层/防火墙限制',
            }

        if not ping_ok and port_open_count == 0:
            return {
                'status': 'unreachable',
                'fault_layer': 'network',
                'description': '目标主机不可达，网络层存在问题',
            }

        # 全部正常
        return {
            'status': 'reachable',
            'fault_layer': 'none',
            'description': '目标主机网络连通正常',
        }
