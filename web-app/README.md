# 运维管理系统 (Ops Manager Web) V1.6

> 面向企业网络运维的综合管理 Web 平台，采用深信服科技风格 UI，覆盖攻击事件、配置变更、工单、设备台账、IP 扫描、网络诊断、群晖用户管理等核心功能。

本目录是 `ops-manager` monorepo 的 **web-app** 子项目。

---

## 功能特性

| 模块 | 功能说明 |
|------|---------|
| **首页概览** | 统计卡片展示攻击事件、配置变更、工单、设备数量及最近动态 |
| **中控大屏** | 深色科技感数据可视化大屏，Chart.js 图表展示趋势与分布 |
| **攻击事件管理** | 记录网络安全攻击事件，支持 severity 分级和状态追踪 |
| **配置变更管理** | 网络设备配置变更记录，支持回滚标记和变更原因追溯 |
| **桌面运维工单** | 工单全生命周期管理：提交 → 分配 → 处理 → 关闭 |
| **设备台账** | 资产设备管理，含 SSH/Telnet 远程管理凭据 |
| **群晖用户管理** | 通过 DSM Web API 扫描全部本地用户，支持筛选、CSV 导出、单个/批量改密与审计 |
| **IP 存活扫描** | 多线程 ICMP ping 扫描，支持 CIDR 网段，结果自动保存，分页展示 |
| **安全事件中心** | CVE 漏洞库、安全资讯聚合展示 |
| **周报月报** | 自动生成运维数据报表，支持打印导出 |
| **快捷导航** | 常用系统链接管理，支持凭据记录 |
| **配置备份** | 网络设备配置备份管理 |
| **系统监控** | 服务器资源监控（CPU/内存/磁盘/网络） |
| **网络诊断** | Ping / Traceroute / 端口探测 / DNS / 一键诊断 |

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Flask 3.0+ |
| ORM | Flask-SQLAlchemy 3.1+ |
| 数据库 | SQLite（开发）/ PostgreSQL（生产建议） |
| 前端 UI | Bootstrap 5.3 + Bootstrap Icons |
| 图表 | Chart.js |
| 模板引擎 | Jinja2 |

---

## 目录结构

```
web-app/
├── app/                    # 应用主目录
│   ├── __init__.py         # 应用工厂函数
│   ├── config.py           # 配置
│   ├── extensions.py       # 扩展初始化（db 等）
│   ├── models.py           # 数据模型
│   ├── routes/             # 视图路由
│   ├── services/           # 业务逻辑层
│   └── api/                # RESTful API
├── templates/              # Jinja2 模板
├── tools/
│   └── nas_users_cli.py    # 群晖用户管理命令行工具（复用 web 服务层）
├── tests/                  # 自动化测试
├── run.py                  # 启动入口
├── requirements.txt        # 依赖列表
├── VERSION.md              # 版本说明
└── README.md               # 本文件
```

---

## 快速开始

### 环境要求

- Python 3.10+
- pip

### 安装依赖

```bash
cd web-app
pip install -r requirements.txt
```

### 启动应用

```bash
python run.py
```

应用默认运行在 `http://0.0.0.0:5000`，浏览器访问 `http://127.0.0.1:5000`。

### 首次运行

首次启动会自动：

1. 创建 SQLite 数据库（`web-app/ops.db`）
2. 初始化默认快捷导航链接

---

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `SECRET_KEY` | Flask 密钥（生产环境务必修改） | `dev-secret-key-2026-ops-manager` |
| `SESSION_COOKIE_SECURE` | 仅通过 HTTPS 发送会话 Cookie | `false` |
| `NAS_SESSION_TTL` | 群晖会话空闲超时（秒） | `1800` |
| `NAS_MAX_SESSIONS` | 进程内最多保留的群晖会话数 | `100` |
| `NAS_MAX_BATCH` | 单次批量改密用户数上限 | `500` |
| `NAS_ALLOWED_HOSTS` | 可选群晖主机白名单，逗号分隔；`.corp.local` 支持子域名 | 空（不限制） |
| `NAS_DEFAULT_VERIFY_SSL` | 群晖连接页是否默认勾选 TLS 校验 | `true` |

### 数据库

默认使用 SQLite，文件位于 `web-app/ops.db`。生产环境建议迁移至 PostgreSQL：

```python
# app/config.py
SQLALCHEMY_DATABASE_URI = 'postgresql://user:password@localhost/ops_manager'
```

---

## 群晖用户管理（Web 模块）

访问 `/nas/users/` 可：

1. 通过 DSM Web API 登录（支持双重验证、HTTPS、自签名证书）
2. 扫描全部本地用户，展示用户组、管理员、密码策略、上次改密、2FA
3. 单个 / 批量修改密码，支持 CSV 导出与审计日志
4. 改密前读取并保留用户原有属性，避免覆盖描述、邮箱、过期时间等

> 需要**独立的单文件脚本**（不依赖本 Web 工程）时，请使用同仓库的
> [synology-user-manager](../synology-user-manager) 子项目。

### 命令行工具

本子项目内置一个复用 Web 服务层的 CLI：

```bash
cd web-app
python tools/nas_users_cli.py list --host 192.168.1.10 --account admin
python tools/nas_users_cli.py reset --host 192.168.1.10 --account admin --users alice,bob --new-password-stdin < new_password.txt
```

---

## API 接口

### RESTful API v1

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/attacks/` | GET/POST | 攻击事件列表/创建 |
| `/api/v1/attacks/<id>` | GET/PUT/DELETE | 攻击事件详情/更新/删除 |
| `/api/v1/configs/` | GET/POST | 配置变更列表/创建 |
| `/api/v1/configs/<id>` | GET/PUT/DELETE | 配置变更详情/更新/删除 |

### 诊断接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/diagnosis/ping` | POST | Ping 连通性测试 |
| `/diagnosis/traceroute` | POST | 路由追踪 |
| `/diagnosis/port_scan` | POST | 端口探测 |
| `/diagnosis/dns` | POST | DNS 解析 |
| `/diagnosis/full` | POST | 一键综合诊断 |

### 群晖用户管理路由

| 端点 | 方法 | 说明 |
|------|------|------|
| `/nas/users/` | GET | 连接页或用户列表 |
| `/nas/users/connect` | POST | 登录 DSM 并扫描用户 |
| `/nas/users/refresh` | POST | 重新扫描 |
| `/nas/users/reset` | POST | 单个/批量改密 |
| `/nas/users/export` | GET | 导出当前筛选结果为 CSV |
| `/nas/users/disconnect` | POST | 注销 DSM 会话 |
| `/nas/users/result/clear` | POST | 清除批量结果面板 |

---

## 测试

```bash
cd web-app
python -m unittest discover -s tests -v
```

覆盖：网络诊断工具箱（输入校验 / 命令注入防护 / 路由）、群晖用户模块（DSM 客户端 / 会话 / 改密属性保护 / 路由 / CSRF / 管理员保护）。

---

## 安全提示

⚠️ **生产环境部署前请务必**：

1. 修改 `SECRET_KEY` 环境变量
2. 关闭 Flask Debug 模式
3. 使用生产级 WSGI 服务器（如 Gunicorn/uWSGI）
4. 配置 HTTPS
5. 完善用户认证机制（当前版本无登录验证）
6. 群晖模块具备重置 NAS 用户密码的能力：不要直接暴露到公网，建议仅监听 `127.0.0.1` 或置于带认证的反向代理之后

---

## 更新日志

### V1.6 (2026-10-29)
- 新增群晖 NAS 用户管理模块（Web + CLI）
- 新增 `tools/nas_users_cli.py`
- 新增群晖模块自动化测试
- 补齐 `requirements.txt` 完整运行依赖

### V1.5 (2026-06-14)
- 深信服科技风格 UI 全面改版
- IP 扫描记录支持删除和分页显示
- 新增网络连通性诊断工具箱

---

## 相关子项目

- [synology-user-manager](../synology-user-manager)：独立的群晖用户扫描 / 批量改密单文件脚本
- [auto-ssh-backup](../auto-ssh-backup)：华三交换机配置批量保存
