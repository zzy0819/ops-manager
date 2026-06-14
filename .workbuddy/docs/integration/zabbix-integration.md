# Zabbix 集成方案

> 运维管理系统 V2.0 — 第三方集成方案（Zabbix）  
> 版本：1.0  
> 日期：2026-05-24

---

## 1. 集成场景分析

运维管理系统与 Zabbix 之间存在双向数据流，核心集成场景如下：

### 场景一：Zabbix 告警自动录入攻击事件（Zabbix → 运维管理系统）

**场景描述**：Zabbix 监控到异常（如 CPU 飙升、流量异常、端口扫描等）触发告警后，自动将告警信息推送到运维管理系统，创建攻击事件记录。

**业务价值**：
- 安全事件零延迟入库，缩短从发现到响应的时间窗口
- 避免"Zabbix 有告警但运维系统无记录"的信息孤岛
- 为后续告警通知中心提供事件源

**数据流**：Zabbix Trigger/Event → Webhook/Script → 运维管理系统 API → 攻击事件表

### 场景二：设备台账与 Zabbix 主机双向同步（双向）

**场景描述**：运维管理系统的设备台账与 Zabbix 的 Host 配置保持同步。新设备录入台账时可自动在 Zabbix 创建监控主机；Zabbix 中新增的主机也可反向同步到设备台账。

**业务价值**：
- 消除设备信息重复维护的工作量
- 确保监控覆盖与资产台账一致，避免漏监控
- IP 存活扫描结果可联动 Zabbix 监控状态

**数据流**：
- 运维管理系统 → Zabbix：设备台账 CRUD → Zabbix API `host.create/update/delete`
- Zabbix → 运维管理系统：Zabbix API `host.get` 定时拉取 → 设备台账同步

### 场景三：监控数据聚合到中控大屏（Zabbix → 运维管理系统）

**场景描述**：中控大屏和首页概览集成 Zabbix 的实时监控数据（CPU、内存、网络流量、在线率等），替代或补充现有的 IP 存活扫描数据。

**业务价值**：
- 大屏展示从"存活扫描"升级为"全维度监控"，信息密度大幅提升
- 运维人员无需切换系统即可掌握全局设备健康状态
- 为自动巡检模块提供数据源

**数据流**：Zabbix API `history.get`/`trend.get` → 运维管理系统后端聚合 → 前端 Chart.js 渲染

### 场景四：运维管理系统工单关联 Zabbix 告警（双向）

**场景描述**：桌面运维工单可关联 Zabbix 告警事件，告警自动创建工单；工单处理完成后可回写 Zabbix 事件确认状态。

**业务价值**：
- 告警到工单的闭环管理，避免告警无人响应
- 工单流转审批模块有真实事件驱动
- 操作审计日志可追溯"告警→工单→处置"全链路

**数据流**：
- Zabbix → 运维管理系统：告警触发 → 自动创建工单
- 运维管理系统 → Zabbix：工单完成 → Zabbix API `event.acknowledge`

### 场景五：IP 存活扫描结果联动 Zabbix 监控（运维管理系统 → Zabbix）

**场景描述**：IP 存活扫描发现新上线设备后，可自动在 Zabbix 中添加 ICMP 监控；扫描发现下线设备可在 Zabbix 中标记。

**业务价值**：
- 新设备自动纳入监控，零人工干预
- 与设备台账联动形成"发现→入账→监控"自动化流水线

**数据流**：IP 存活扫描结果 → 判定新增/离线 → Zabbix API `host.create/update`

---

## 2. Zabbix 侧能力梳理

### 2.1 Zabbix API

Zabbix 提供 JSON-RPC 风格的 API（`/api_jsonrpc.php`），覆盖所有配置与查询操作。

| 能力 | API 方法 | 集成用途 |
|------|---------|---------|
| 主机管理 | `host.create/get/update/delete` | 设备台账双向同步 |
| 触发器管理 | `trigger.create/get/update` | 告警规则映射 |
| 事件查询 | `event.get` | 告警事件拉取、工单关联 |
| 事件确认 | `event.acknowledge` | 工单完成回写 |
| 历史数据 | `history.get` | 大屏实时监控数据 |
| 趋势数据 | `trend.get` | 大屏趋势图表 |
| 问题查询 | `problem.get` | 当前活跃告警 |
| 用户认证 | `user.login` | API Token 获取 |

**认证方式**：用户名密码获取 Token，或 Zabbix 5.4+ 使用 API Token（推荐）。

### 2.2 Webhook Media Type

Zabbix 4.4+ 内置 Webhook 告警推送能力，可在 Action 中配置，将告警以 HTTP POST 推送到指定 URL。

**关键配置项**：
- URL：运维管理系统 Webhook 接收端点
- HTTP 方法：POST
- 请求体：自定义 JavaScript 模板，可提取 `{EVENT.ID}`、`{EVENT.NAME}`、`{TRIGGER.SEVERITY}` 等宏
- 认证：Bearer Token / Basic Auth

### 2.3 Zabbix Sender / Trapper

- **Zabbix Sender**：命令行工具，可主动向 Zabbix Server 发送指标数据（`zabbix_sender -z server -s host -k item -o value`）
- **Zabbix Trapper Item**：被动接收数据的 Item 类型，配合 Sender 使用

**集成用途**：运维管理系统的 IP 存活扫描结果、安全事件统计等指标，可通过 Sender 推送到 Zabbix，在 Zabbix 侧展示运维数据。

### 2.4 Zabbix 主动抓取（Zabbix Agent）

Zabbix Agent 可采集服务器本地指标（CPU、内存、磁盘、网络等），为场景三提供原始数据。此部分属于 Zabbix 自有能力，集成时仅需通过 API 读取结果。

---

## 3. 各场景技术实现路径

### 3.1 场景一：Zabbix 告警自动录入攻击事件

**实现方式：Webhook Media Type 推送**

```
Zabbix Trigger 触发
  → Action 匹配
    → Webhook Media Type 执行
      → HTTP POST 到 运维管理系统 /api/v1/webhooks/zabbix/alert
        → 后端解析告警，创建攻击事件
          → 触发告警通知中心（V2.0）
```

**Webhook 请求体模板（Zabbix 侧配置）**：

```javascript
{
    "event_id": "{EVENT.ID}",
    "event_name": "{EVENT.NAME}",
    "event_time": "{EVENT.DATE} {EVENT.TIME}",
    "trigger_id": "{TRIGGER.ID}",
    "trigger_name": "{TRIGGER.NAME}",
    "trigger_severity": "{TRIGGER.SEVERITY}",
    "host_name": "{HOST.NAME}",
    "host_ip": "{HOST.IP}",
    "item_key": "{ITEM.KEY}",
    "item_value": "{ITEM.VALUE}",
    "recovery": "{EVENT.RECOVERY.VALUE}",
    "tags": "{EVENT.TAGS}"
}
```

**后端接收端点设计**：

```python
# webhooks.py
@webhook_bp.route('/zabbix/alert', methods=['POST'])
def receive_zabbix_alert():
    data = request.get_json()
    
    # 严重程度映射
    severity_map = {
        'Not classified': '低危',
        'Information': '低危', 
        'Warning': '中危',
        'Average': '中危',
        'High': '高危',
        'Disaster': '严重'
    }
    
    # 攻击类型推断（基于 Trigger 名称/Item Key 关键词匹配）
    attack_type = infer_attack_type(data['trigger_name'], data['item_key'])
    
    event = AttackEvent(
        attack_type=attack_type,
        source_ip=data.get('host_ip', 'unknown'),
        target_ip=data.get('host_ip', 'unknown'),
        severity=severity_map.get(data['trigger_severity'], '中危'),
        status='待处理',
        title=data['event_name'],
        description=f"Zabbix Event ID: {data['event_id']}\n"
                    f"Trigger: {data['trigger_name']}\n"
                    f"Host: {data['host_name']} ({data['host_ip']})\n"
                    f"Item Value: {data['item_value']}",
        source='zabbix',
        source_event_id=data['event_id']
    )
    db.session.add(event)
    db.session.commit()
    
    # 触发告警通知中心
    trigger_notification(event)
    
    return jsonify({'status': 'ok', 'event_id': event.id}), 201
```

**攻击类型推断逻辑**：

```python
ATTACK_TYPE_RULES = {
    'DDoS': ['ddos', 'flood', 'traffic_spike', 'bps_high'],
    '端口扫描': ['port_scan', 'portscan', 'new_port'],
    '暴力破解': ['brute', 'login_fail', 'auth_fail', 'ssh_fail'],
    '恶意软件': ['malware', 'virus', 'trojan', 'ransomware'],
    'WebShell': ['webshell', 'web_shell'],
    '其他': []  # 默认
}

def infer_attack_type(trigger_name, item_key=''):
    text = f"{trigger_name} {item_key}".lower()
    for attack_type, keywords in ATTACK_TYPE_RULES.items():
        if any(kw in text for kw in keywords):
            return attack_type
    return '其他'
```

**安全防护**：
- Webhook 端点验证请求签名（HMAC-SHA256，预共享密钥）
- 速率限制：单 IP 每分钟最多 100 次请求
- 幂等处理：基于 `source + source_event_id` 去重

### 3.2 场景二：设备台账与 Zabbix 主机双向同步

**实现方式：Zabbix API 调用 + 定时同步任务**

#### 运维管理系统 → Zabbix（实时）

```python
# zabbix_sync.py
class ZabbixHostSync:
    def __init__(self, zabbix_url, api_token):
        self.url = f"{zabbix_url}/api_jsonrpc.php"
        self.token = api_token
    
    def _call(self, method, params=None):
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "auth": self.token,
            "id": 1
        }
        resp = requests.post(self.url, json=payload)
        return resp.json().get('result')
    
    def create_host(self, device):
        """设备台账新增 → Zabbix 创建主机"""
        params = {
            "host": device.name,
            "interfaces": [{
                "type": 1,  # Agent
                "main": 1,
                "useip": 1,
                "ip": device.ip,
                "dns": "",
                "port": "10050"
            }],
            "groups": [{"groupid": self._get_group_id(device.type)}],
            "templates": [{"templateid": self._get_template_id(device.type)}],
            "inventory_mode": 0,
            "inventory": {
                "location": device.location,
                "serialno_a": device.serial_number,
                "vendor": device.brand
            }
        }
        return self._call('host.create', params)
    
    def update_host(self, device):
        """设备台账修改 → Zabbix 更新主机"""
        host = self._find_host_by_ip(device.ip)
        if not host:
            return self.create_host(device)
        params = {
            "hostid": host['hostid'],
            "host": device.name,
            "inventory": {
                "location": device.location,
                "serialno_a": device.serial_number,
                "vendor": device.brand
            }
        }
        return self._call('host.update', params)
    
    def delete_host(self, device):
        """设备台账删除 → Zabbix 删除主机"""
        host = self._find_host_by_ip(device.ip)
        if host:
            return self._call('host.delete', [host['hostid']])
```

#### Zabbix → 运维管理系统（定时拉取）

```python
# 在 APScheduler 定时任务中执行
def sync_zabbix_hosts_to_inventory():
    """每 30 分钟从 Zabbix 拉取主机列表，同步到设备台账"""
    zabbix_hosts = zabbix_sync._call('host.get', {
        "output": ["host", "name", "status"],
        "selectInterfaces": ["ip", "dns", "port"],
        "selectGroups": ["name"],
        "selectInventory": ["location", "serialno_a", "vendor"]
    })
    
    for zh in zabbix_hosts:
        ip = zh['interfaces'][0]['ip'] if zh['interfaces'] else None
        if not ip:
            continue
        
        device = Device.query.filter_by(ip=ip).first()
        if device:
            # 更新已有设备
            device.name = zh['host']
            device.zabbix_hostid = zh['hostid']
            device.zabbix_status = 'monitored' if zh['status'] == '0' else 'unmonitored'
            if zh.get('inventory'):
                device.location = zh['inventory'].get('location', device.location)
        else:
            # 新增设备（标记为 Zabbix 来源）
            device = Device(
                name=zh['host'],
                ip=ip,
                source='zabbix',
                zabbix_hostid=zh['hostid']
            )
            db.session.add(device)
    
    db.session.commit()
```

**冲突处理策略**：
- 以最后修改时间为准（Last Write Wins）
- Zabbix 来源的设备在台账中标记 `source='zabbix'`，手动创建的标记 `source='manual'`
- IP 冲突时：以运维管理系统为主，Zabbix 侧更新

### 3.3 场景三：监控数据聚合到中控大屏

**实现方式：Zabbix API 数据查询 + 后端缓存**

```python
# zabbix_dashboard.py
from flask import jsonify
from functools import lru_cache
import time

class ZabbixDashboard:
    def __init__(self, zabbix_sync):
        self.zabbix = zabbix_sync
    
    @lru_cache(maxsize=128)
    def _cached_history(self, itemid, time_from, time_till, cache_seconds=60):
        """带缓存的指标查询"""
        return self.zabbix._call('history.get', {
            "output": "extend",
            "itemids": itemid,
            "history": 0,  # 浮点型
            "time_from": time_from,
            "time_till": time_till,
            "sortfield": "clock",
            "sortorder": "ASC"
        })
    
    def get_device_health_overview(self):
        """获取所有被监控设备的健康概览"""
        hosts = self.zabbix._call('host.get', {
            "output": ["host", "name"],
            "selectInterfaces": ["ip"],
            "filter": {"status": 0}  # 仅监控中
        })
        
        result = []
        for host in hosts:
            problems = self.zabbix._call('problem.get', {
                "output": ["eventid", "severity", "name"],
                "hostids": host['hostid'],
                "recent": True
            })
            result.append({
                'host': host['host'],
                'ip': host['interfaces'][0]['ip'] if host['interfaces'] else '',
                'problem_count': len(problems),
                'max_severity': max((int(p['severity']) for p in problems), default=0),
                'status': 'normal' if not problems else 'warning'
            })
        return result
    
    def get_top_metrics(self, item_key_pattern, limit=10):
        """获取 Top N 指标（如 CPU Top10）"""
        items = self.zabbix._call('item.get', {
            "output": ["itemid", "name", "hostid"],
            "search": {"key_": item_key_pattern},
            "limit": limit
        })
        # 获取最新值
        for item in items:
            history = self.zabbix._call('history.get', {
                "output": "extend",
                "itemids": item['itemid'],
                "history": 0,
                "sortfield": "clock",
                "sortorder": "DESC",
                "limit": 1
            })
            item['lastvalue'] = history[0]['value'] if history else None
        return items
```

**前端集成**：

```javascript
// 在 Chart.js 图表组件中新增 Zabbix 数据源
async function loadZabbixMetrics(metricType) {
    const resp = await fetch(`/api/v1/zabbix/dashboard/${metricType}`);
    const data = await resp.json();
    
    // 渲染到已有的 Chart.js 实例
    if (metricType === 'device_health') {
        updateDeviceHealthChart(data);
    } else if (metricType === 'cpu_top') {
        updateTopChart('cpuChart', data);
    }
}
```

**性能优化**：
- 后端 Redis 缓存指标数据，TTL 30-60 秒
- 大屏数据定时推送（WebSocket / SSE），前端无需轮询
- 批量查询替代逐条查询

### 3.4 场景四：工单关联 Zabbix 告警

**实现方式：双向 API 调用**

#### 告警自动创建工单

```python
# zabbix_ticket_integration.py
def create_ticket_from_alert(alert_data):
    """Zabbix 告警自动创建工单"""
    priority_map = {
        '低危': '低',
        '中危': '中',
        '高危': '高',
        '严重': '紧急'
    }
    
    ticket = WorkOrder(
        ticket_no=generate_ticket_no(),  # 自动编号
        applicant='系统自动',
        department='运维部',
        problem_type='安全告警',
        priority=priority_map.get(alert_data['severity'], '中'),
        status='待分配',
        title=f"[安全告警] {alert_data['title']}",
        description=alert_data['description'],
        related_event_id=alert_data['event_id'],
        related_zabbix_event=alert_data['source_event_id']
    )
    db.session.add(ticket)
    db.session.commit()
    return ticket
```

#### 工单完成回写 Zabbix

```python
def acknowledge_zabbix_event(ticket):
    """工单关闭后确认 Zabbix 事件"""
    if not ticket.related_zabbix_event:
        return
    
    zabbix_sync._call('event.acknowledge', {
        "eventids": ticket.related_zabbix_event,
        "action": 6,  # ACK + 添加消息
        "message": f"运维系统工单 {ticket.ticket_no} 已处理完成。处理人: {ticket.handler}"
    })
```

### 3.5 场景五：IP 存活扫描联动 Zabbix

```python
def sync_scan_result_to_zabbix(scan_results):
    """扫描结果同步到 Zabbix"""
    for result in scan_results:
        host = zabbix_sync._find_host_by_ip(result.ip)
        
        if result.is_alive and not host:
            # 新上线设备 → 创建 Zabbix 主机（仅 ICMP 监控）
            zabbix_sync._call('host.create', {
                "host": f"auto-{result.ip}",
                "interfaces": [{
                    "type": 1, "main": 1, "useip": 1,
                    "ip": result.ip, "dns": "", "port": "10050"
                }],
                "groups": [{"groupid": ZABBIX_AUTO_GROUP_ID}],
                "templates": [{"templateid": ICMP_TEMPLATE_ID}]
            })
        elif not result.is_alive and host:
            # 设备离线 → 更新 Zabbix 主机状态
            zabbix_sync._call('host.update', {
                "hostid": host['hostid'],
                "status": 1  # 取消监控
            })
```

---

## 4. 数据映射

### 4.1 Zabbix Host → 设备台账（Device）

| Zabbix 字段 | 运维管理系统字段 | 映射说明 |
|-------------|----------------|---------|
| `host.host` | `Device.name` | 主机名 |
| `hostid` | `Device.zabbix_hostid` | 新增字段，存储 Zabbix 主机 ID |
| `interfaces[0].ip` | `Device.ip` | 主 IP |
| `interfaces[0].dns` | `Device.dns_name` | 新增字段 |
| `interfaces[0].port` | `Device.agent_port` | 新增字段 |
| `groups[0].name` | `Device.type` | 通过映射表转换 |
| `inventory.location` | `Device.location` | 位置 |
| `inventory.serialno_a` | `Device.serial_number` | 序列号 |
| `inventory.vendor` | `Device.brand` | 品牌 |
| `status` | `Device.zabbix_status` | 新增字段：monitored/unmonitored |
| — | `Device.source` | 新增字段：manual/zabbix/sangfor |
| — | `Device.last_synced_at` | 新增字段：最后同步时间 |

### 4.2 Zabbix Trigger/Event → 攻击事件（AttackEvent）

| Zabbix 字段 | 运维管理系统字段 | 映射说明 |
|-------------|----------------|---------|
| `event.eventid` | `AttackEvent.source_event_id` | 新增字段，Zabbix 事件 ID |
| — | `AttackEvent.source` | 新增字段，固定值 `zabbix` |
| `event.name` / `trigger.name` | `AttackEvent.title` | 新增字段，事件标题 |
| `trigger.description` | `AttackEvent.description` | 详细描述 |
| `trigger.severity` | `AttackEvent.severity` | 通过映射表转换（见 3.1） |
| — | `AttackEvent.attack_type` | 通过关键词推断（见 3.1） |
| `interfaces[0].ip` | `AttackEvent.source_ip` | 被攻击目标 IP |
| — | `AttackEvent.target_ip` | 同 source_ip（Zabbix 侧无攻击源信息） |
| `event.clock` | `AttackEvent.discovered_at` | 事件时间 |
| — | `AttackEvent.status` | 初始值 `待处理` |
| `event.tags` | `AttackEvent.tags` | 新增字段，JSON 存储 |

### 4.3 Zabbix Item → 大屏指标

| Zabbix Item Key | 大屏指标 | 用途 |
|----------------|---------|-----|
| `system.cpu.util` | CPU 使用率 | 设备健康度 |
| `vm.memory.util` | 内存使用率 | 设备健康度 |
| `vfs.fs.util` | 磁盘使用率 | 设备健康度 |
| `net.if.in[eth0]` | 入流量 | 网络监控 |
| `net.if.out[eth0]` | 出流量 | 网络监控 |
| `icmpping` | ICMP 存活 | 替代/补充 IP 扫描 |
| `system.uptime` | 运行时长 | 设备稳定性 |

---

## 5. 集成优先级分阶段

### 第一阶段：基础接入（P0，2-3 周）

| 序号 | 场景 | 实现内容 | 依赖 |
|------|------|---------|------|
| 1 | 场景一 | Zabbix Webhook → 攻击事件自动录入 | 告警通知中心、Webhook 端点 |
| 2 | 场景一 | 攻击类型推断与严重程度映射 | 攻击事件模型扩展 |
| 3 | 基础 | Zabbix API 连接配置（URL/Token 管理） | 配置管理 |

**交付物**：Zabbix 告警自动录入功能上线，Webhook 接收端点 + 数据映射 + 去重。

### 第二阶段：数据同步（P1，2-3 周）

| 序号 | 场景 | 实现内容 | 依赖 |
|------|------|---------|------|
| 1 | 场景二 | 设备台账 → Zabbix 主机同步（新增/修改/删除） | Device 模型扩展 |
| 2 | 场景二 | Zabbix 主机 → 设备台账定时同步 | APScheduler |
| 3 | 场景五 | IP 存活扫描 → Zabbix 自动添加监控 | IP 扫描模块 |

**交付物**：设备台账与 Zabbix 双向同步，IP 扫描联动 Zabbix 监控。

### 第三阶段：数据展示（P2，2 周）

| 序号 | 场景 | 实现内容 | 依赖 |
|------|------|---------|------|
| 1 | 场景三 | 大屏集成 Zabbix 设备健康概览 | 中控大屏模块 |
| 2 | 场景三 | Top N 指标图表（CPU/内存/流量） | Chart.js |
| 3 | 场景三 | 指标缓存与性能优化 | Redis |

**交付物**：中控大屏展示 Zabbix 监控数据，替代部分 IP 扫描展示。

### 第四阶段：工单闭环（P3，2 周）

| 序号 | 场景 | 实现内容 | 依赖 |
|------|------|---------|------|
| 1 | 场景四 | Zabbix 告警自动创建工单 | 工单流转审批 |
| 2 | 场景四 | 工单关闭回写 Zabbix 事件确认 | Zabbix API |
| 3 | 全场景 | 操作审计日志记录所有 Zabbix API 调用 | 操作审计日志 |

**交付物**：告警→工单→处置闭环，审计日志覆盖 Zabbix 集成操作。

---

## 6. 对现有需求的影响

### 6.1 数据模型变更

| 模型 | 变更内容 | 影响范围 |
|------|---------|---------|
| AttackEvent | 新增字段：`source`、`source_event_id`、`title`、`tags` | 攻击事件 CRUD、筛选、报表 |
| Device | 新增字段：`zabbix_hostid`、`zabbix_status`、`dns_name`、`agent_port`、`source`、`last_synced_at` | 设备台账 CRUD |
| WorkOrder | 新增字段：`related_zabbix_event` | 工单管理 |

### 6.2 V2.0 需求联动

| V2.0 需求 | Zabbix 集成影响 |
|-----------|----------------|
| 用户认证(RBAC) | 需新增 `zabbix_admin`、`zabbix_viewer` 角色权限，控制 Zabbix 配置与数据访问 |
| 告警通知中心 | Zabbix 是核心事件源，需设计事件来源标识与路由规则 |
| 自动巡检 | 可复用 Zabbix 监控数据作为巡检项，减少 Agent 部署 |
| 工单流转审批 | 告警自动创建工单需要与审批流程配合，需定义"自动工单"的审批规则 |
| 操作审计日志 | 所有 Zabbix API 调用需记录审计日志，包括操作人、操作类型、目标资源 |
| API 完善 | 需新增 `/api/v1/zabbix/*` 系列 API 端点 |
| Webhook 集成 | Zabbix Webhook 是首个 Webhook 集成实例，需设计通用 Webhook 框架 |

### 6.3 基础设施依赖

| 依赖项 | 说明 |
|--------|------|
| Redis | 监控数据缓存，减少 Zabbix API 调用频率 |
| APScheduler | 定时同步任务（Zabbix → 设备台账） |
| HTTPS | Zabbix API 与 Webhook 通信建议走 HTTPS |
| 网络连通 | 运维管理系统需能访问 Zabbix Server 的 API 端口（默认 80/443） |

### 6.4 配置管理

需在系统设置中新增 Zabbix 连接配置：

```python
# 配置项
ZABBIX_URL = 'https://zabbix.example.com'
ZABBIX_API_TOKEN = 'xxxxxxxx'
ZABBIX_WEBHOOK_SECRET = 'hmac_shared_secret'
ZABBIX_SYNC_INTERVAL = 1800  # 秒，同步间隔
ZABBIX_DEFAULT_GROUP = 'Auto-Discovered'  # 自动发现设备分组
ZABBIX_ICMP_TEMPLATE_ID = '10081'  # ICMP 模板 ID
```

---

## 附录：Zabbix API 常用调用示例

### 获取认证 Token

```bash
curl -X POST https://zabbix.example.com/api_jsonrpc.php \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "user.login",
    "params": {"username": "Admin", "password": "zabbix"},
    "id": 1
  }'
```

### 查询活跃问题

```bash
curl -X POST https://zabbix.example.com/api_jsonrpc.php \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "problem.get",
    "params": {"output": "extend", "recent": true},
    "auth": "TOKEN_HERE",
    "id": 1
  }'
```

### 确认事件

```bash
curl -X POST https://zabbix.example.com/api_jsonrpc.php \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "event.acknowledge",
    "params": {
      "eventids": ["12345"],
      "action": 6,
      "message": "已通过运维系统处理"
    },
    "auth": "TOKEN_HERE",
    "id": 1
  }'
```
