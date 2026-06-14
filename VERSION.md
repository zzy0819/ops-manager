# 运维管理系统 - 版本 V1.4

## 版本信息
- 版本号：V1.4
- 发布日期：2026-05-24
- 技术栈：Python Flask + SQLAlchemy + SQLite + Bootstrap 5

## 功能模块
1. 网络安全攻击事件管理（CRUD + 多维筛选）
2. 网络配置变更记录管理（CRUD + 多维筛选）
3. 桌面运维工单管理（CRUD + 自动编号 + 多维筛选）
4. 网络设备台账管理（CRUD + 多维筛选）
5. 系统快速跳转（数据库驱动）
6. 内网 IP 存活扫描（ICMP Ping + 多线程）
7. 中控大屏 Dashboard（Chart.js + 实时刷新）
8. 首页统计概览（5 个 KPI 指标卡片）
9. 周报/月报一键生成与导出（Excel / PDF）
10. 安全事件中心（NVD CVE 漏洞 + 国内外安全资讯 RSS 聚合）
11. API v1 接口（/api/v1/attacks、/api/v1/configs）
12. Swagger/OpenAPI 文档（/api/openapi.json、/api/docs）
13. 监控端点（/monitor/health、/metrics、/info）

## V1.4 更新内容
- P0 架构优化：路由层不再直接操作数据库，所有 DB 访问统一走服务层
  - main.py：index() 和 dashboard() 共 30+ 次 ORM 查询迁移至 MainService
  - ip_scan.py：扫描逻辑、线程管理、DB 操作全部迁移至 IPScanService
  - quick_access.py：CRUD 操作迁移至 QuickLinkService
  - monitor.py：指标查询迁移至 MonitorService
- 新增服务层模块：MainService、QuickLinkService、MonitorService
- 重构 IPScanService：完整扫描编排、进度管理、结果存储一站式闭环

## V1.3 更新内容
- 周报/月报页面重构为 Tab 标签页布局，解决数据量增长导致页面无限延伸问题
- 修复 9 个 Bug（包含常量不一致、分页越界 404、Flask-SQLAlchemy 3.x API 兼容性等）
- IP 扫描优化：200 线程并发，/24 网段扫描从约 4 分钟缩短至 2-3 秒
- IP 扫描结果页新增可视化组件（IP 矩阵、饼图、实时进度条、一键复制）
- 修复 IP 扫描线程上下文错误及模板渲染问题

## V1.1 更新内容
- 项目重构为模块化架构（Blueprint / Factory Pattern）
- 新增安全事件中心：NVD 近 3 天 CVE 漏洞 + 6 个国内 + 2 个国际安全资讯源
- 新增周报/月报生成与导出（Excel 多工作表、PDF 打印优化）
- 侧边栏导航扁平化，视觉统一优化
- 数据库连接池优化（pool_size=5, pool_pre_ping=True）
- 支持 PyInstaller 打包为独立可执行文件

## 运行方式
```bash
pip install flask flask-sqlalchemy requests feedparser openpyxl
python run.py
```
或直接运行打包好的 exe：
```
ops_manager.exe
```
访问 http://localhost:5000