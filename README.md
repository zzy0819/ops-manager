# 运维管理系统 (Ops Manager)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0%2B-green)](https://flask.palletsprojects.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 一款面向企业网络运维的综合管理平台，采用深信服科技风格 UI 设计，支持攻击事件管理、配置变更追踪、桌面运维工单、设备台账、IP 存活扫描等核心功能。

---

## 功能特性

### 核心模块

| 模块 | 功能说明 |
|------|---------|
| **首页概览** | 统计卡片展示攻击事件、配置变更、工单、设备数量及最近动态 |
| **中控大屏** | 深色科技感数据可视化大屏，Chart.js 图表展示趋势与分布 |
| **攻击事件管理** | 记录网络安全攻击事件，支持 severity（低/中/高/严重）分级和状态追踪 |
| **配置变更管理** | 网络设备配置变更记录，支持回滚标记和变更原因追溯 |
| **桌面运维工单** | 工单全生命周期管理：提交 → 分配 → 处理 → 关闭 |
| **设备台账** | 资产设备管理，含 SSH/Telnet 远程管理凭据 |
| **IP 存活扫描** | 多线程 ICMP ping 扫描，支持 CIDR 网段，结果自动保存，分页展示 |
| **安全事件中心** | CVE 漏洞库、安全资讯聚合展示 |
| **周报月报** | 自动生成运维数据报表，支持打印导出 |
| **快捷导航** | 常用系统链接管理，支持凭据记录 |
| **配置备份** | 网络设备配置备份管理 |
| **系统监控** | 服务器资源监控（CPU/内存/磁盘/网络） |

### UI 风格

- **深信服科技风格**：深蓝渐变侧边栏、科技蓝主色调 `#1677ff`、青色强调 `#00d4ff`
- **响应式布局**：适配桌面端和移动端
- **深色中控大屏**：独立的数据可视化展示界面

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

## 快速开始

### 环境要求

- Python 3.10+
- pip

### 安装依赖

```bash
pip install -r requirements.txt
```

> 注：当前 `requirements.txt` 仅包含核心依赖。完整运行还需安装 `requests`、`feedparser`、`openpyxl`、`psutil`，建议根据运行报错补充安装。

### 启动应用

```bash
python run.py
```

应用默认运行在 `http://0.0.0.0:5000`

### 首次运行

首次启动会自动：
1. 创建 SQLite 数据库（`ops.db`）
2. 初始化默认快捷导航链接

---

## 项目结构

```
ops-manager/
├── app/                    # 应用主目录
│   ├── __init__.py         # 应用工厂函数
│   ├── config.py           # 配置文件
│   ├── extensions.py       # 扩展初始化（db 等）
│   ├── models.py           # 数据模型（SQLAlchemy）
│   ├── routes/             # 视图路由
│   │   ├── main.py         # 首页/中控大屏
│   │   ├── attacks.py      # 攻击事件
│   │   ├── configs.py      # 配置变更
│   │   ├── tickets.py      # 运维工单
│   │   ├── devices.py      # 设备台账
│   │   ├── ip_scan.py      # IP 扫描
│   │   ├── reports.py      # 周报月报
│   │   ├── security.py     # 安全事件中心
│   │   ├── monitor.py      # 系统监控
│   │   ├── quick_access.py # 快捷导航
│   │   └── config_backup.py# 配置备份
│   ├── services/           # 业务逻辑层
│   │   ├── ip_scan_service.py
│   │   └── ...
│   └── api/                # RESTful API
│       ├── docs.py         # API 文档
│       └── v1/             # API v1 版本
│           ├── attacks.py
│           └── configs.py
├── templates/              # Jinja2 模板
├── static/                 # 静态资源
├── scans/                  # IP 扫描结果文件（自动创建）
├── ops.db                  # SQLite 数据库（自动创建）
├── run.py                  # 启动入口
├── requirements.txt        # 依赖列表
└── README.md               # 本文件
```

---

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `SECRET_KEY` | Flask 密钥（生产环境务必修改） | `dev-secret-key-2026-ops-manager` |

### 数据库

默认使用 SQLite，文件位于项目根目录 `ops.db`。

生产环境建议迁移至 PostgreSQL：

```python
# app/config.py
SQLALCHEMY_DATABASE_URI = 'postgresql://user:password@localhost/ops_manager'
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

### 内部接口

| 端点 | 说明 |
|------|------|
| `/ip-scan/scan-progress/<scan_id>` | IP 扫描实时进度（AJAX 轮询） |

---

## 开发计划

详见 `.workbuddy/memory/MEMORY.md` 中的 V2.0 需求规划：

- **P0**: 用户认证与权限控制、操作审计日志、API 体系完善
- **P1**: 告警通知、自动巡检、趋势分析报表、批量操作、工单审批流程
- **P2**: SLA 监控仪表盘、全局搜索增强

---

## 安全提示

⚠️ **生产环境部署前请务必**：

1. 修改 `SECRET_KEY` 环境变量
2. 关闭 Flask Debug 模式
3. 使用生产级 WSGI 服务器（如 Gunicorn/uWSGI）
4. 配置 HTTPS
5. 完善用户认证机制（当前版本无登录验证）

---

## 开源协议

[MIT License](LICENSE)

---

## 致谢

- UI 设计参考深信服科技产品风格
- 图标库：[Bootstrap Icons](https://icons.getbootstrap.com)
- 图表库：[Chart.js](https://www.chartjs.org)
