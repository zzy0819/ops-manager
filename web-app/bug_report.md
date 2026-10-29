# 运维管理系统 Bug 测试报告

**测试时间**: 2026-05-24  
**测试方式**: Flask test_client 自动化测试 + 静态代码审查  
**测试范围**: 全部路由、表单提交、数据库查询、报告导出

---

## 一、测试结论摘要

| 类别 | 数量 |
|------|------|
| 严重 Bug（功能完全错误） | 4 |
| 中等 Bug（影响用户体验） | 2 |
| 低危 / 潜在风险 | 3 |
| 路由测试通过率 | 17/17 (404 为预期行为除外) |

---

## 二、严重 Bug（功能完全错误）

### 🔴 BUG-1：报告中攻击事件「按严重程度」统计永远为 0

**文件**: `app/routes/reports.py`  
**根因**: `reports.py` 定义的严重程度常量与 `models.py` 实际存储值不一致

```python
# reports.py（错误）
ATTACK_SEVERITIES = ['低', '中', '高', '严重']

# models.py（实际存储）
SEVERITY_LIST = ['低危', '中危', '高危', '严重']
```

- `"低"` ≠ `"低危"`，`"中"` ≠ `"中危"`，`"高"` ≠ `"高危"`
- **影响**: 报告页面和 Excel 导出中按严重程度的攻击统计全部显示 0，数据严重失真

---

### 🔴 BUG-2：报告中攻击事件「按类型」统计错误

**文件**: `app/routes/reports.py`  
**根因**: 攻击类型常量与模型不一致

```python
# reports.py（错误）
ATTACK_TYPES = ['DDoS', 'SQL注入', 'XSS', '暴力破解', '端口扫描', '恶意软件', '钓鱼攻击', 'DNS劫持', '中间人攻击', '其他']

# models.py（实际存储）
TYPE_LIST = ['DDoS', 'SQL注入', 'XSS', 'CSRF', '端口扫描', '暴力破解', '恶意软件', '钓鱼', 'WebShell', '其他']
```

差异项：
- `"钓鱼攻击"` vs `"钓鱼"` → 报告中钓鱼类攻击统计为 0
- `"CSRF"`、`"WebShell"` 在报告中不存在 → 这两类攻击永远不会被统计
- 报告独有 `"DNS劫持"`、`"中间人攻击"` → 也永远为 0

---

### 🔴 BUG-3：报告中配置变更「按类型」统计全部为 0

**文件**: `app/routes/reports.py`  
**根因**: 配置类型常量与模型完全对不上

```python
# reports.py（错误）
CONFIG_TYPES = ['防火墙规则', '交换机配置', '路由器配置', 'ACL策略', 'VPN配置', 'VLAN配置', '负载均衡', '其他']

# models.py（实际存储）
CONFIG_TYPE_LIST = ['路由', '防火墙', '交换机', '服务器', '负载均衡', 'VPN', 'DNS', '其他']
```

- **影响**: 除了"其他"偶尔匹配，其余所有配置类型统计结果全为 0

---

### 🔴 BUG-4：报告中配置变更「已回滚」状态统计永远为 0

**文件**: `app/routes/reports.py`  
**根因**: 查询的状态字符串与实际存储值不匹配

```python
# reports.py（错误）
config_by_status['回滚'] = ConfigChange.query.filter(..., change_status == '回滚').count()

# models.py 实际存储的是
STATUS_LIST = ['成功', '失败', '已回滚']
```

- `"回滚"` ≠ `"已回滚"`
- **已通过数据库验证**: 插入一条 `change_status='已回滚'` 的记录，用 `'回滚'` 查询结果为 0，用 `'已回滚'` 查询结果为 1

---

## 三、中等 Bug（影响用户体验）

### 🟡 BUG-5：分页越界时返回 404 而非空页面

**文件**: `app/routes/attacks.py`, `configs.py`, `tickets.py`, `devices.py`  
**根因**: Flask-SQLAlchemy `paginate()` 默认在页码超出范围时抛出 404

```
GET /attacks/?page=999 => HTTP 404
GET /tickets/?page=999 => HTTP 404
GET /configs/?page=999 => HTTP 404
GET /devices/?page=999 => HTTP 404
```

- **影响**: 用户在删除最后一条记录后，若当前在最后一页，可能看到 404 错误页面
- **建议**: `paginate(error_out=False)` 可改为返回空集合而非 404

---

### 🟡 BUG-6：SECRET_KEY 每次重启随机生成

**文件**: `app/config.py`  
**代码**: `SECRET_KEY = os.urandom(24).hex()`

- **影响**: 服务器每次重启后，所有用户的 session 失效，flash 消息丢失
- **建议**: 从环境变量或固定配置文件读取 SECRET_KEY

---

## 四、低危 / 潜在风险

### 🟢 BUG-7：SQLite 不支持连接池参数

**文件**: `app/config.py`

```python
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 5,
    'pool_recycle': 3600,
    'pool_pre_ping': True,
}
```

SQLite 使用 `StaticPool`，`pool_size` / `pool_recycle` 参数无效，SQLAlchemy 在某些版本下会输出警告。

---

### 🟢 BUG-8：IP 扫描后台线程操作数据库存在并发风险

**文件**: `app/routes/ip_scan.py`  
- `scan_ip_range()` 在后台线程中执行 `IPScanResult.query.get(scan_id)` + `db.session.commit()`
- 虽然有 `with app.app_context()`，但 SQLite 在高频写入时可能出现 `database is locked` 错误

---

### 🟢 BUG-9：`Model.query.get_or_404()` 在 Flask-SQLAlchemy 3.x 已 Deprecated

**文件**: 所有 routes 文件  
- 所有 CRUD 的 edit/delete 路由均使用 `Model.query.get_or_404(id)`
- Flask-SQLAlchemy 3.1 已标记 `.query` 为 legacy API，推荐改用 `db.session.get()`
- 目前功能正常，但升级 Flask 版本时可能导致问题

---

## 五、测试通过的功能

| 功能 | 状态 |
|------|------|
| 首页 / 中控大屏 | ✅ 正常 |
| 攻击事件列表、新增、编辑、删除 | ✅ 正常 |
| 配置变更列表、新增、编辑、删除 | ✅ 正常 |
| 工单管理列表、新增、编辑、删除 | ✅ 正常 |
| 设备台账列表、新增、编辑、删除 | ✅ 正常 |
| IP 扫描（页面） | ✅ 正常 |
| 快捷导航增删改 | ✅ 正常 |
| 安全事件中心 | ✅ 正常 |
| 报告页面（周报/月报/自定义） | ✅ 页面可渲染，但统计数据有 BUG |
| Excel 导出 | ✅ 文件可下载，但数据统计有 BUG |
| PDF（打印视图） | ✅ 正常 |
| 搜索和筛选 | ✅ 正常 |
| 数据库初始化 | ✅ 正常 |

---

## 六、修复优先级建议

| 优先级 | Bug | 影响 |
|--------|-----|------|
| P0 — 立刻修复 | BUG-1/2/3/4 | 报告数据完全失真 |
| P1 — 近期修复 | BUG-5/6 | 用户体验问题 |
| P2 — 待优化 | BUG-7/8/9 | 低风险技术债务 |
