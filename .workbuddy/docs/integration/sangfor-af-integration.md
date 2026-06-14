# 深信服 AF（下一代防火墙）集成方案

> 运维管理系统 V2.0 — 第三方集成方案（深信服 AF）  
> 版本：1.0  
> 日期：2026-05-24

---

## 1. 深信服 AF 概述与核心能力

### 1.1 产品定位

深信服下一代防火墙（AF，Next-Generation Firewall）是深信服科技推出的企业级安全网关产品，集成了传统防火墙、IPS、WAF、APT 防御、URL 过滤等能力，定位于网络边界安全防护。

### 1.2 核心安全能力

| 能力 | 说明 |
|------|------|
| 访问控制 | 基于 IP/端口/协议/应用/用户的五元组策略控制 |
| IPS（入侵防御） | 内置入侵特征库，实时检测并阻断攻击行为 |
| WAF（Web 应用防火墙） | SQL 注入、XSS、CSRF、WebShell 等 Web 攻击防护 |
| APT 防御 | 恶意文件检测、C2 通信检测、沙箱分析 |
| 僵木蠕勒防护 | 僵尸网络、木马、蠕虫、勒索软件检测 |
| DDoS 防护 | 流量型与应用型 DDoS 攻击检测与清洗 |
| URL 过滤 | 恶意站点/钓鱼站点访问拦截 |
| SSL/TLS 解密 | 加密流量解密检测 |
| VPN | IPsec/SSL VPN 接入 |
| 用户认证 | 本地/AD/LDAP/RADIUS 认证 |

### 1.3 与运维管理系统的关联

运维管理系统当前已具备攻击事件管理模块（10 种攻击类型），深信服 AF 的安全日志可直接映射为攻击事件数据源，极大丰富系统的安全感知能力。同时，AF 的配置变更可与配置变更管理模块联动。

---

## 2. 集成场景分析

### 场景一：AF 安全日志自动录入攻击事件（AF → 运维管理系统）

**场景描述**：深信服 AF 检测到的安全事件（入侵防御、WAF 拦截、APT 检测、DDoS 防护等）自动推送到运维管理系统，创建攻击事件记录。

**业务价值**：
- 安全事件从"边界设备检测"到"运维系统入库"零延迟
- AF 的丰富日志字段（攻击类型、载荷、规则 ID）极大增强攻击事件的信息完整度
- 10 种攻击类型中，AF 可直接覆盖 DDoS、SQL 注入、XSS、CSRF、端口扫描、暴力破解、恶意软件、钓鱼、WebShell 共 9 种

**数据流**：AF 安全日志 → Syslog/Webhook/API → 运维管理系统 → 攻击事件表

### 场景二：AF 配置变更同步（AF → 运维管理系统）

**场景描述**：深信服 AF 的策略变更、安全配置变更自动同步到运维管理系统的配置变更管理模块，记录每次变更的详细信息。

**业务价值**：
- 防火墙策略变更直接影响安全边界，必须纳入配置变更管理
- 满足合规审计要求：防火墙变更可追溯
- 与操作审计日志联动，记录"谁在什么时间修改了什么策略"

**数据流**：AF 操作日志 → Syslog → 运维管理系统 → 配置变更表

### 场景三：攻击事件联动 AF 封堵（运维管理系统 → AF）

**场景描述**：运维管理人员在攻击事件详情页一键下发封堵指令到深信服 AF，将攻击源 IP 加入黑名单或临时封堵策略。

**业务价值**：
- 从"发现攻击"到"阻断攻击源"闭环，响应时间从分钟级降到秒级
- 减少运维人员登录 AF 控制台的手动操作
- 封堵操作自动记录审计日志

**数据流**：运维管理系统 UI → API → AF RESTful API → 策略下发 → 结果回写

### 场景四：AF 安全事件统计与报告联动（AF → 运维管理系统）

**场景描述**：深信服 AF 的安全统计数据（攻击趋势、Top 攻击类型、Top 攻击源等）聚合到运维管理系统的周报/月报和安全事件中心。

**业务价值**：
- 周报/月报从"人工编写"升级为"数据驱动"，AF 数据丰富报告内容
- 安全事件中心获得实时安全态势数据，与 NVD CVE/RSS 形成互补
- 中控大屏展示实时安全态势

**数据流**：AF API 统计查询 → 运维管理系统后端 → 报表/大屏/安全事件中心

### 场景五：AF 威胁情报与安全事件中心联动（双向）

**场景描述**：AF 的威胁情报（恶意 IP、恶意域名、C2 地址等）与安全事件中心的 CVE/RSS 聚合联动，形成"威胁情报→漏洞→攻击事件"关联分析。

**业务价值**：
- CVE 披露后可查询 AF 是否已有对应攻击拦截记录
- AF 检测到的新威胁可联动 CVE 库查看相关漏洞信息
- 提升安全运营的关联分析能力

**数据流**：
- AF → 运维管理系统：威胁指标 → 安全事件中心关联查询
- 运维管理系统 → AF：CVE 相关 IP/域名 → AF 策略加固建议

---

## 3. AF 侧接口能力

### 3.1 RESTful API

深信服 AF 提供 RESTful API（需在 AF 管理界面开启 API 访问），支持策略管理、日志查询、系统配置等操作。

| 能力 | API 端点 | 说明 |
|------|---------|------|
| 认证 | `POST /api/v1.0.0/login` | 获取访问 Token |
| 安全日志查询 | `GET /api/v1.0.0/log/security` | 分页查询安全日志 |
| 攻击日志查询 | `GET /api/v1.0.0/log/attack` | 分页查询攻击日志 |
| 流量日志查询 | `GET /api/v1.0.0/log/traffic` | 分页查询流量日志 |
| 策略管理 | `GET/POST/PUT/DELETE /api/v1.0.0/policy/security` | 安全策略 CRUD |
| 地址对象管理 | `GET/POST/PUT/DELETE /api/v1.0.0/object/address` | IP 地址组管理（用于封堵） |
| 黑名单管理 | `POST /api/v1.0.0/security/blacklist` | IP 黑名单增删改查 |
| 系统信息 | `GET /api/v1.0.0/system/info` | AF 设备信息 |
| 统计报表 | `GET /api/v1.0.0/report/security` | 安全统计报表数据 |

> **注意**：具体 API 端点以实际 AF 版本为准，不同版本 API 路径可能有差异。AF 8.0+ 版本 API 能力更完善。

**认证方式**：用户名密码登录获取 Token，Token 有效期默认 30 分钟，需实现自动续期。

### 3.2 Syslog 外发

深信服 AF 支持将日志以 Syslog 格式外发到指定服务器（UDP 514 / TCP 514 / TLS），可配置日志类型和级别。

**支持的日志类型**：
- 安全日志（入侵防御、WAF、APT 等）
- 流量日志
- 操作日志（配置变更、管理员登录等）
- 系统日志

**Syslog 格式**：支持标准 BSD Syslog 和结构化 Syslog（RFC 5424），部分版本支持 CEF（Common Event Format）格式。

### 3.3 Webhook 外发

部分新版本 AF 支持 Webhook 外发能力，可将特定安全事件以 HTTP POST 推送到指定 URL。

**限制**：
- 不是所有 AF 版本均支持 Webhook
- 推送格式和字段不可完全自定义
- 建议优先使用 Syslog 或 API 方式

### 3.4 日志导出

AF 管理界面支持手动导出日志（CSV/PCAP），适合一次性历史数据导入场景，不建议作为持续集成方式。

---

## 4. 各场景技术实现路径

### 4.1 场景一：AF 安全日志自动录入攻击事件

**推荐实现方式：Syslog 外发 + 本地 Syslog Server**

```
AF 安全事件触发
  → AF Syslog 外发（CEF 格式）
    → 运维管理系统 Syslog Server（TCP 1514）
      → CEF 解析器
        → 字段映射
          → 创建攻击事件
            → 触发告警通知中心
```

#### Syslog Server 实现

```python
# syslog_server.py
import socketserver
import re
from datetime import datetime

class SyslogUDPHandler(socketserver.BaseRequestHandler):
    """接收 AF 发送的 Syslog 消息"""
    
    def handle(self):
        data = self.request[0].decode('utf-8', errors='ignore')
        try:
            event = parse_sangfor_cef(data)
            if event:
                process_sangfor_event(event)
        except Exception as e:
            app.logger.error(f"Syslog parse error: {e}")


def start_syslog_server(host='0.0.0.0', port=1514):
    server = socketserver.ThreadingUDPServer((host, port), SyslogUDPHandler)
    server.serve_forever()
```

#### CEF 格式解析

深信服 AF 的 Syslog 输出通常遵循 CEF（Common Event Format）格式：

```
CEF:0|Sangfor|AF|8.0|1001|SQL Injection Detected|7|src=192.168.1.100 dst=10.0.0.1 dpt=80 proto=TCP msg=SQL Injection attempt detected in HTTP request act=block cn1=1001 cn1Label=RuleId suser=admin request=http://10.0.0.1/login?id=1' OR '1'='1
```

```python
# cef_parser.py
import re

CEF_PATTERN = re.compile(
    r'CEF:(?P<version>\d+)\|(?P<device_vendor>[^|]*)\|(?P<device_product>[^|]*)\|'
    r'(?P<device_version>[^|]*)\|(?P<signature_id>[^|]*)\|(?P<name>[^|]*)\|'
    r'(?P<severity>[^|]*)\|(?P<extension>.*)'
)

def parse_sangfor_cef(raw_message):
    """解析深信服 AF CEF 格式日志"""
    match = CEF_PATTERN.search(raw_message)
    if not match:
        return None
    
    result = match.groupdict()
    
    # 解析扩展字段
    extension = result.pop('extension', '')
    ext_fields = parse_extension(extension)
    result.update(ext_fields)
    
    # 标准化
    result['severity'] = int(result['severity'])  # 0-10
    result['src'] = ext_fields.get('src', 'unknown')
    result['dst'] = ext_fields.get('dst', 'unknown')
    result['dpt'] = ext_fields.get('dpt', '')
    result['proto'] = ext_fields.get('proto', '')
    result['action'] = ext_fields.get('act', 'detect')
    result['rule_id'] = ext_fields.get('cn1', '')
    
    return result


def parse_extension(extension_str):
    """解析 CEF 扩展字段"""
    fields = {}
    # key=value 格式解析
    for token in re.finditer(r'(\w+)=([^\s]+(?:\s+[^\s=]+)*?)(?=\s+\w+=|$)', extension_str):
        fields[token.group(1)] = token.group(2).strip()
    return fields
```

#### AF 攻击类型到系统攻击类型的映射

```python
# sangfor_mapping.py
SANGFOR_ATTACK_TYPE_MAP = {
    # AF 检测类型 → 运维管理系统攻击类型
    'sql_injection': 'SQL注入',
    'xss': 'XSS',
    'csrf': 'CSRF',
    'ddos': 'DDoS',
    'port_scan': '端口扫描',
    'brute_force': '暴力破解',
    'malware': '恶意软件',
    'phishing': '钓鱼',
    'webshell': 'WebShell',
    'apt': '恶意软件',
    'botnet': '恶意软件',
    'trojan': '恶意软件',
    'ransomware': '恶意软件',
    'worm': '恶意软件',
    'c2_communication': '恶意软件',
    'waf_sql_injection': 'SQL注入',
    'waf_xss': 'XSS',
    'waf_csrf': 'CSRF',
    'waf_webshell': 'WebShell',
}

# 基于 signature_id 或 name 关键词的映射
ATTACK_TYPE_KEYWORD_RULES = {
    'SQL注入': ['sql injection', 'sql_injection', 'sqli'],
    'XSS': ['xss', 'cross-site scripting', 'cross_site_scripting'],
    'CSRF': ['csrf', 'cross-site request forgery'],
    'DDoS': ['ddos', 'flood', 'syn flood', 'udp flood', 'icmp flood'],
    '端口扫描': ['port scan', 'portscan', 'scan detect'],
    '暴力破解': ['brute force', 'brute_force', 'login fail', 'password crack'],
    '恶意软件': ['malware', 'trojan', 'botnet', 'ransomware', 'worm', 'apt', 'c2', 'backdoor'],
    '钓鱼': ['phishing', 'phish', 'fraud'],
    'WebShell': ['webshell', 'web shell', 'backdoor web'],
}

def map_attack_type(af_event):
    """将 AF 事件映射为系统攻击类型"""
    # 优先使用直接映射
    sig_id = af_event.get('signature_id', '')
    if sig_id in SANGFOR_ATTACK_TYPE_MAP:
        return SANGFOR_ATTACK_TYPE_MAP[sig_id]
    
    # 基于名称关键词匹配
    name = af_event.get('name', '').lower()
    for attack_type, keywords in ATTACK_TYPE_KEYWORD_RULES.items():
        if any(kw in name for kw in keywords):
            return attack_type
    
    return '其他'
```

#### 严重程度映射

```python
SEVERITY_MAP = {
    # CEF Severity (0-10) → 运维管理系统严重程度
    range(0, 3): '低危',    # 0-2
    range(3, 6): '中危',    # 3-5
    range(6, 9): '高危',    # 6-8
    range(9, 11): '严重',   # 9-10
}

def map_severity(cef_severity):
    """CEF 严重程度映射"""
    sev = int(cef_severity)
    for sev_range, level in SEVERITY_MAP.items():
        if sev in sev_range:
            return level
    return '中危'
```

#### 事件处理入库

```python
def process_sangfor_event(af_event):
    """处理 AF 事件并创建攻击事件"""
    # 去重检查
    existing = AttackEvent.query.filter_by(
        source='sangfor_af',
        source_event_id=af_event['signature_id']
    ).filter(
        AttackEvent.discovered_at >= datetime.now() - timedelta(minutes=5)
    ).first()
    if existing:
        return existing
    
    attack_type = map_attack_type(af_event)
    severity = map_severity(af_event['severity'])
    
    event = AttackEvent(
        attack_type=attack_type,
        source_ip=af_event['src'],
        target_ip=af_event['dst'],
        target_port=af_event.get('dpt', ''),
        severity=severity,
        status='待处理',
        title=af_event['name'],
        description=format_event_description(af_event),
        source='sangfor_af',
        source_event_id=af_event['signature_id'],
        raw_log=af_event,  # 原始日志 JSON
        action_taken=af_event.get('action', 'detect'),  # AF 采取的动作
        protocol=af_event.get('proto', ''),
        rule_id=af_event.get('rule_id', '')
    )
    db.session.add(event)
    db.session.commit()
    
    # 触发告警通知中心
    trigger_notification(event)
    
    return event


def format_event_description(af_event):
    """格式化事件描述"""
    parts = [
        f"深信服 AF 安全事件",
        f"检测规则: {af_event.get('name', 'N/A')} (ID: {af_event.get('signature_id', 'N/A')})",
        f"攻击源: {af_event['src']} → 目标: {af_event['dst']}:{af_event.get('dpt', 'N/A')}",
        f"协议: {af_event.get('proto', 'N/A')}",
        f"AF 处置动作: {af_event.get('action', 'detect')}",
    ]
    if af_event.get('msg'):
        parts.append(f"详情: {af_event['msg']}")
    if af_event.get('request'):
        parts.append(f"请求URL: {af_event['request']}")
    return '\n'.join(parts)
```

**备用实现方式：API 定时拉取**

当 Syslog 不可用时，可通过 AF API 定时拉取安全日志：

```python
def pull_sangfor_security_logs(since_minutes=5):
    """定时从 AF API 拉取安全日志"""
    token = get_sangfor_token()
    time_from = int((datetime.now() - timedelta(minutes=since_minutes)).timestamp())
    
    resp = requests.get(
        f"{SANGFOR_AF_URL}/api/v1.0.0/log/security",
        headers={'Authorization': f'Bearer {token}'},
        params={'time_from': time_from, 'limit': 1000}
    )
    
    for log_entry in resp.json().get('data', []):
        event = convert_api_log_to_event(log_entry)
        process_sangfor_event(event)
```

### 4.2 场景二：AF 配置变更同步

**实现方式：Syslog 操作日志 → 配置变更记录**

```python
def process_sangfor_config_change(af_event):
    """处理 AF 配置变更事件"""
    # AF 操作日志中的配置变更
    change = ConfigChange(
        device_name=f"深信服AF-{SANGFOR_AF_IP}",
        device_ip=SANGFOR_AF_IP,
        config_type='安全策略',
        change_content=af_event.get('msg', ''),
        operator=af_event.get('suser', 'unknown'),
        is_rolled_back=False,
        change_time=datetime.now(),
        source='sangfor_af',
        detail=af_event
    )
    db.session.add(change)
    db.session.commit()
    
    # 记录操作审计日志
    audit_log(
        action='af_config_change',
        operator=change.operator,
        target=f"AF策略变更: {change.change_content}",
        source='sangfor_af'
    )
```

**AF Syslog 配置**：
- 日志类型：操作日志
- 外发目标：运维管理系统 Syslog Server（TCP 1514）
- 级别：informational 及以上

### 4.3 场景三：攻击事件联动 AF 封堵

**实现方式：RESTful API 策略下发**

```python
# sangfor_block.py
class SangforAFBlocker:
    """深信服 AF 封堵操作封装"""
    
    def __init__(self, af_url, username, password):
        self.af_url = af_url
        self.username = username
        self.password = password
        self._token = None
        self._token_expires = None
    
    def _ensure_token(self):
        """确保 Token 有效"""
        if self._token and self._token_expires and datetime.now() < self._token_expires:
            return self._token
        
        resp = requests.post(f"{self.af_url}/api/v1.0.0/login", json={
            "username": self.username,
            "password": self.password
        })
        data = resp.json()
        self._token = data['token']
        self._token_expires = datetime.now() + timedelta(minutes=25)
        return self._token
    
    def block_ip(self, ip, duration=3600, reason='运维系统封堵'):
        """将 IP 加入 AF 黑名单"""
        token = self._ensure_token()
        
        resp = requests.post(
            f"{self.af_url}/api/v1.0.0/security/blacklist",
            headers={'Authorization': f'Bearer {token}'},
            json={
                "ip": ip,
                "duration": duration,  # 封堵时长（秒），0=永久
                "description": f"[运维系统自动封堵] {reason}",
                "type": "blacklist"
            }
        )
        
        if resp.status_code == 200:
            # 记录审计日志
            audit_log(
                action='af_block_ip',
                operator=current_user.username,
                target=f"封堵IP: {ip}, 时长: {duration}s",
                result='success'
            )
            return {'status': 'ok', 'ip': ip}
        else:
            audit_log(
                action='af_block_ip',
                operator=current_user.username,
                target=f"封堵IP: {ip}",
                result='failed',
                detail=resp.text
            )
            return {'status': 'error', 'message': resp.text}
    
    def unblock_ip(self, ip):
        """将 IP 从 AF 黑名单移除"""
        token = self._ensure_token()
        resp = requests.delete(
            f"{self.af_url}/api/v1.0.0/security/blacklist",
            headers={'Authorization': f'Bearer {token}'},
            json={"ip": ip}
        )
        audit_log(
            action='af_unblock_ip',
            operator=current_user.username,
            target=f"解封IP: {ip}",
            result='success' if resp.status_code == 200 else 'failed'
        )
        return resp.json()
```

**前端一键封堵按钮**：

```python
# attack_events.py
@event_bp.route('/api/v1/events/<int:event_id>/block', methods=['POST'])
def block_attack_source(event_id):
    """一键封堵攻击源 IP"""
    event = AttackEvent.query.get_or_404(event_id)
    
    if event.source_ip in ('unknown', '127.0.0.1', '0.0.0.0'):
        return jsonify({'error': '无法封堵无效源IP'}), 400
    
    blocker = SangforAFBlocker(SANGFOR_AF_URL, SANGFOR_AF_USER, SANGFOR_AF_PASS)
    result = blocker.block_ip(
        ip=event.source_ip,
        duration=request.json.get('duration', 3600),
        reason=f"攻击事件 #{event.id}: {event.attack_type}"
    )
    
    if result['status'] == 'ok':
        event.status = '已封堵'
        event.action_taken = 'block'
        db.session.commit()
    
    return jsonify(result)
```

### 4.4 场景四：AF 安全事件统计与报告联动

**实现方式：API 数据聚合**

```python
# sangfor_report.py
class SangforReportIntegration:
    """AF 报表与运维管理系统周报/月报联动"""
    
    def get_security_summary(self, days=7):
        """获取 AF 安全统计摘要"""
        token = self._ensure_token()
        time_from = int((datetime.now() - timedelta(days=days)).timestamp())
        
        resp = requests.get(
            f"{self.af_url}/api/v1.0.0/report/security",
            headers={'Authorization': f'Bearer {token}'},
            params={'time_from': time_from}
        )
        data = resp.json().get('data', {})
        
        return {
            'total_attacks': data.get('total_attacks', 0),
            'blocked_attacks': data.get('blocked_attacks', 0),
            'top_attack_types': data.get('top_attack_types', []),
            'top_source_ips': data.get('top_source_ips', []),
            'top_target_ips': data.get('top_target_ips', []),
            'attack_trend': data.get('attack_trend', []),
        }
    
    def enrich_weekly_report(self, report):
        """将 AF 数据注入周报"""
        af_data = self.get_security_summary(days=7)
        
        report.af_summary = {
            'total_attacks': af_data['total_attacks'],
            'blocked_rate': (
                af_data['blocked_attacks'] / af_data['total_attacks'] * 100
                if af_data['total_attacks'] > 0 else 0
            ),
            'top_attack_types': af_data['top_attack_types'][:5],
            'top_source_ips': af_data['top_source_ips'][:10]
        }
        return report
```

**安全事件中心展示**：

```python
@security_center_bp.route('/api/v1/security-center/sangfor-overview')
def sangfor_overview():
    """安全事件中心 - AF 概览数据"""
    integration = SangforReportIntegration()
    data = integration.get_security_summary(days=30)
    
    # 与 NVD CVE 数据关联
    recent_cves = get_recent_cves(days=30)
    
    return jsonify({
        'af_stats': data,
        'correlation': correlate_attacks_with_cves(data, recent_cves),
        'last_updated': datetime.now().isoformat()
    })
```

### 4.5 场景五：威胁情报与安全事件中心联动

```python
def correlate_attacks_with_cves(af_data, cve_data):
    """AF 攻击数据与 CVE 关联分析"""
    correlations = []
    
    for attack in af_data.get('top_attack_types', []):
        # 根据 AF 攻击类型搜索相关 CVE
        related_cves = []
        for cve in cve_data:
            if is_attack_related_to_cve(attack, cve):
                related_cves.append({
                    'cve_id': cve.cve_id,
                    'cvss_score': cve.cvss_score,
                    'description': cve.description[:100]
                })
        
        if related_cves:
            correlations.append({
                'attack_type': attack['type'],
                'attack_count': attack['count'],
                'related_cves': related_cves[:5],
                'risk_level': 'high' if any(c['cvss_score'] >= 9.0 for c in related_cves) else 'medium'
            })
    
    return correlations


def is_attack_related_to_cve(attack, cve):
    """判断攻击类型是否与 CVE 相关"""
    attack_type = attack.get('type', '').lower()
    cve_desc = cve.description.lower() if cve.description else ''
    
    type_keyword_map = {
        'SQL注入': ['sql injection', 'sqli'],
        'XSS': ['xss', 'cross-site scripting'],
        'CSRF': ['csrf', 'cross-site request forgery'],
        'DDoS': ['denial of service', 'dos', 'ddos'],
        'WebShell': ['webshell', 'remote code execution', 'rce'],
        '恶意软件': ['malware', 'trojan', 'backdoor', 'ransomware'],
    }
    
    keywords = type_keyword_map.get(attack_type, [])
    return any(kw in cve_desc for kw in keywords)
```

---

## 5. 数据映射

### 5.1 AF 安全日志字段 → 攻击事件模型

| AF CEF 字段 | 运维管理系统字段 | 映射说明 |
|-------------|----------------|---------|
| `signature_id` (cn1) | `AttackEvent.source_event_id` | AF 规则 ID |
| — | `AttackEvent.source` | 固定值 `sangfor_af` |
| `name` | `AttackEvent.title` | 事件标题 |
| `msg` | `AttackEvent.description`（部分） | 事件详情 |
| `severity` (0-10) | `AttackEvent.severity` | 通过映射表转换（低危/中危/高危/严重） |
| `src` | `AttackEvent.source_ip` | 攻击源 IP |
| `dst` | `AttackEvent.target_ip` | 攻击目标 IP |
| `dpt` | `AttackEvent.target_port` | 新增字段，目标端口 |
| `proto` | `AttackEvent.protocol` | 新增字段，协议类型 |
| `act` | `AttackEvent.action_taken` | 新增字段，AF 处置动作（block/detect/allow） |
| — | `AttackEvent.attack_type` | 通过规则推断（见 4.1） |
| `request` | `AttackEvent.request_url` | 新增字段，请求 URL |
| `suser` | `AttackEvent.username` | 新增字段，关联用户 |
| `device_product` | — | 校验来源为 `AF` |
| — | `AttackEvent.raw_log` | 新增字段，原始日志 JSON |
| — | `AttackEvent.rule_id` | 新增字段，AF 规则 ID |

### 5.2 AF 操作日志字段 → 配置变更模型

| AF 操作日志字段 | 运维管理系统字段 | 映射说明 |
|----------------|----------------|---------|
| — | `ConfigChange.device_name` | 固定格式 `深信服AF-{IP}` |
| — | `ConfigChange.device_ip` | AF 管理 IP |
| 操作类型 | `ConfigChange.config_type` | 映射：策略变更/对象变更/系统配置 |
| 操作详情 | `ConfigChange.change_content` | 变更描述 |
| 操作人 | `ConfigChange.operator` | AF 管理员账号 |
| — | `ConfigChange.is_rolled_back` | 初始值 False |
| — | `ConfigChange.source` | 新增字段，固定值 `sangfor_af` |

### 5.3 AF 严重程度 → 系统严重程度

| AF CEF Severity | 系统严重程度 | 说明 |
|-----------------|------------|------|
| 0-2 | 低危 | 信息类、低风险 |
| 3-5 | 中危 | 中等风险攻击 |
| 6-8 | 高危 | 高风险攻击 |
| 9-10 | 严重 | 紧急威胁 |

### 5.4 AF 攻击动作 → 系统状态

| AF 动作 (act) | 系统攻击事件状态 | 说明 |
|--------------|----------------|------|
| `block` | `已拦截` | AF 已阻断 |
| `detect` | `待处理` | AF 仅检测未阻断，需人工处理 |
| `allow` | `已放行` | AF 放行（策略允许），记录备案 |

---

## 6. 与安全事件中心的协同设计

### 6.1 整体架构

```
┌─────────────────────────────────────────────────────┐
│                   安全事件中心                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ NVD CVE  │  │ RSS 聚合 │  │ AF 安全态势(新增) │  │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │
│       │              │                 │             │
│       └──────────────┼─────────────────┘             │
│                      │                               │
│              ┌───────┴───────┐                       │
│              │  关联分析引擎  │                       │
│              └───────┬───────┘                       │
│                      │                               │
│       ┌──────────────┼──────────────┐                │
│       ▼              ▼              ▼                │
│  攻击事件       威胁情报       漏洞预警               │
│  (AF+NVD)      (AF+CVE)       (CVE+AF)              │
└─────────────────────────────────────────────────────┘
```

### 6.2 三维关联分析

| 维度 | 数据源 1 | 数据源 2 | 关联方式 | 输出 |
|------|---------|---------|---------|------|
| 攻击→漏洞 | AF 攻击事件 | NVD CVE | 攻击类型匹配 CVE 关键词 | "该攻击类型存在 N 个相关高危漏洞" |
| 漏洞→攻击 | NVD CVE | AF 攻击事件 | CVE 披露后查询 AF 是否有拦截 | "CVE-XXXX 已被 AF 拦截 N 次" |
| 威胁→情报 | AF 恶意 IP | RSS 安全资讯 | IP/域名在安全资讯中出现 | "该 IP 近期被多个情报源标记" |

### 6.3 安全态势大屏模块

在安全事件中心的大屏视图中新增 AF 安全态势面板：

```javascript
// AF 安全态势面板数据结构
const afDashboardData = {
    // 实时攻击计数
    realtime: {
        attacks_per_minute: 0,
        blocked_rate: 0,
        active_threats: 0
    },
    // 攻击类型分布（饼图）
    attack_type_distribution: [
        { type: 'SQL注入', count: 0 },
        { type: 'XSS', count: 0 },
        // ...
    ],
    // 攻击趋势（折线图，24h）
    attack_trend_24h: [],
    // Top 攻击源（柱状图）
    top_source_ips: [],
    // 地理分布（地图）
    geo_distribution: [],
    // 与 CVE 的关联告警
    cve_correlation_alerts: []
};
```

### 6.4 告警优先级升级规则

当 AF 攻击事件与 CVE 关联时，自动升级严重程度：

| 条件 | 原始严重程度 | 升级后 | 说明 |
|------|------------|--------|------|
| AF 高危攻击 + 关联 CVE CVSS≥9.0 | 高危 | 严重 | 确认可利用的高危漏洞攻击 |
| AF 中危攻击 + 关联 CVE CVSS≥7.0 | 中危 | 高危 | 有CVE佐证的中危攻击 |
| AF 同源 IP 短时间重复攻击 | 按原级别 | 升一级 | 持续攻击行为升级处理 |

---

## 7. 集成优先级分阶段

### 第一阶段：安全日志接入（P0，2-3 周）

| 序号 | 场景 | 实现内容 | 依赖 |
|------|------|---------|------|
| 1 | 场景一 | AF Syslog 外发配置 + Syslog Server | Syslog 接收服务 |
| 2 | 场景一 | CEF 解析器 + 字段映射 + 攻击类型推断 | 攻击事件模型扩展 |
| 3 | 场景一 | 事件去重 + 入库 + 告警通知 | 告警通知中心 |
| 4 | 备用 | AF API 定时拉取（Syslog 不可用时） | AF API 认证 |

**交付物**：AF 安全日志自动录入攻击事件，CEF 解析器，攻击类型与严重程度映射。

### 第二阶段：一键封堵（P1，2 周）

| 序号 | 场景 | 实现内容 | 依赖 |
|------|------|---------|------|
| 1 | 场景三 | AF RESTful API 封堵封装 | AF API 开启 |
| 2 | 场景三 | 攻击事件详情页"一键封堵"按钮 | 前端改造 |
| 3 | 场景三 | 封堵操作审计日志 | 操作审计日志 |
| 4 | 场景三 | 封堵结果回写事件状态 | 攻击事件状态扩展 |

**交付物**：一键封堵功能上线，含封堵/解封/审计。

### 第三阶段：配置变更与报表联动（P2，2 周）

| 序号 | 场景 | 实现内容 | 依赖 |
|------|------|---------|------|
| 1 | 场景二 | AF 操作日志 → 配置变更记录 | Syslog 操作日志 |
| 2 | 场景四 | AF 安全统计 → 周报/月报注入 | 报表模块 |
| 3 | 场景四 | 中控大屏 AF 安全态势面板 | 大屏模块 |
| 4 | 场景四 | 安全事件中心 AF 概览 | 安全事件中心 |

**交付物**：配置变更同步、报表数据丰富、大屏安全态势展示。

### 第四阶段：关联分析与威胁情报（P3，2-3 周）

| 序号 | 场景 | 实现内容 | 依赖 |
|------|------|---------|------|
| 1 | 场景五 | AF 攻击 ↔ CVE 关联分析 | NVD CVE 数据 |
| 2 | 场景五 | 严重程度自动升级规则 | 攻击事件模型 |
| 3 | 场景五 | 威胁情报面板 | 安全事件中心 |
| 4 | 全场景 | 集成健康检查与监控 | 系统监控 |

**交付物**：攻击-漏洞关联分析，威胁情报面板，严重程度自动升级。

---

## 8. 对现有需求的影响

### 8.1 数据模型变更

| 模型 | 变更内容 | 影响范围 |
|------|---------|---------|
| AttackEvent | 新增字段：`source`、`source_event_id`、`title`、`target_port`、`protocol`、`action_taken`、`request_url`、`username`、`raw_log`、`rule_id`、`tags` | 攻击事件 CRUD、筛选、报表 |
| AttackEvent | 新增状态值：`已拦截`、`已放行`（原：待处理/处理中/已处理/已关闭） | 攻击事件状态流转 |
| ConfigChange | 新增字段：`source` | 配置变更管理 |
| Device | 新增字段：`source`、`last_synced_at` | 设备台账（与 Zabbix 共用） |

### 8.2 V2.0 需求联动

| V2.0 需求 | 深信服 AF 集成影响 |
|-----------|-------------------|
| 用户认证(RBAC) | 需新增 `af_operator`（封堵操作权限）、`af_viewer`（AF 日志查看权限）角色 |
| 告警通知中心 | AF 是核心安全事件源，告警量可能较大，需设计告警聚合规则（同源 IP 5 分钟内合并） |
| 自动巡检 | AF 连接状态、规则库版本、策略完整性可作为巡检项 |
| 工单流转审批 | 一键封堵操作需要与审批流程配合：高危封堵需审批，低危可直接执行 |
| 操作审计日志 | 所有 AF API 调用（封堵/解封/查询）需记录审计日志 |
| 知识库 | AF 规则说明、攻击类型处置建议可导入知识库 |
| API 完善 | 需新增 `/api/v1/sangfor/*` 系列 API 端点 |
| Webhook 集成 | AF Webhook（如支持）接入通用 Webhook 框架 |

### 8.3 基础设施依赖

| 依赖项 | 说明 |
|--------|------|
| Syslog Server | 运维管理系统需部署 Syslog 接收服务（UDP/TCP 1514） |
| Redis | 事件去重缓存、AF API Token 缓存 |
| APScheduler | AF API 日志拉取定时任务（备用方案） |
| HTTPS | AF API 通信建议走 HTTPS |
| 网络连通 | 运维管理系统需能访问 AF 管理 IP（API 端口），AF 需能访问 Syslog Server |

### 8.4 AF 侧配置清单

| 配置项 | 说明 | 建议值 |
|--------|------|--------|
| Syslog 外发 | 开启安全日志 + 操作日志 Syslog 外发 | 目标：运维系统 IP:1514，格式：CEF，协议：TCP |
| API 访问 | 开启 RESTful API | 允许运维系统 IP 访问 |
| API 账号 | 创建专用 API 账号 | 最小权限原则：日志查询 + 黑名单管理 |
| Webhook（可选） | 开启 Webhook 外发 | 目标：运维系统 Webhook URL |
| 日志级别 | 安全日志：informational 及以上 | — |

### 8.5 性能与容量预估

| 指标 | 预估值 | 说明 |
|------|--------|------|
| AF 日志量 | 500-5000 条/小时 | 取决于网络流量与策略 |
| Syslog 带宽 | <1 Mbps | 文本日志，带宽占用小 |
| 入库延迟 | <3 秒 | Syslog → 解析 → 入库 |
| API 查询延迟 | 1-5 秒 | 含 AF 响应时间 |
| 封堵操作延迟 | <5 秒 | 从点击到 AF 策略生效 |

### 8.6 安全考虑

| 安全项 | 措施 |
|--------|------|
| Syslog 传输加密 | 使用 TCP + TLS（如 AF 支持） |
| API 认证 | 专用 API 账号 + Token 定期轮换 |
| 封堵操作授权 | 高危封堵需审批，操作需二次确认 |
| 误封堵恢复 | 封堵操作记录审计日志，支持一键解封 |
| API 调用限速 | 后端限制 AF API 调用频率，防止异常批量操作 |
| 日志完整性 | raw_log 字段保留原始日志，支持回溯审计 |

---

## 附录：深信服 AF API 常用调用示例

### 登录获取 Token

```bash
curl -X POST https://10.0.0.1/api/v1.0.0/login \
  -H "Content-Type: application/json" \
  -k \
  -d '{
    "username": "api_user",
    "password": "api_password"
  }'
```

### 查询安全日志

```bash
curl -X GET "https://10.0.0.1/api/v1.0.0/log/security?time_from=1716528000&limit=100" \
  -H "Authorization: Bearer TOKEN_HERE" \
  -k
```

### 添加 IP 黑名单

```bash
curl -X POST https://10.0.0.1/api/v1.0.0/security/blacklist \
  -H "Authorization: Bearer TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -k \
  -d '{
    "ip": "192.168.1.100",
    "duration": 3600,
    "description": "[运维系统封堵] DDoS攻击源",
    "type": "blacklist"
  }'
```

### 查询安全统计

```bash
curl -X GET "https://10.0.0.1/api/v1.0.0/report/security?time_from=1716441600&time_till=1716528000" \
  -H "Authorization: Bearer TOKEN_HERE" \
  -k
```

> **注意**：以上 API 端点为通用参考格式，实际端点路径请以深信服 AF 对应版本的 API 文档为准。建议在集成前与深信服技术支持确认 API 能力与版本兼容性。
