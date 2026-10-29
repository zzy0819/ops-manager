# 运维管理系统 - 版本 V1.6

## 版本信息
- 版本号：V1.6
- 发布日期：2026-10-29
- 技术栈：Python Flask + SQLAlchemy + SQLite + Bootstrap 5

## 功能模块
1. 网络安全攻击事件管理（CRUD + 多维筛选）
2. 网络配置变更记录管理（CRUD + 多维筛选）
3. 桌面运维工单管理（CRUD + 自动编号 + 多维筛选）
4. 网络设备台账管理（CRUD + 多维筛选）
5. 系统快速跳转（数据库驱动）
6. 内网 IP 存活扫描（ICMP Ping + 多线程 + 分页展示 + 删除记录）
7. 中控大屏 Dashboard（Chart.js + 实时刷新）
8. 首页统计概览（5 个 KPI 指标卡片）
9. 周报/月报一键生成与导出（Excel / PDF）
10. 安全事件中心（NVD CVE 漏洞 + 国内外安全资讯 RSS 聚合）
11. API v1 接口（/api/v1/attacks、/api/v1/configs）
12. Swagger/OpenAPI 文档（/api/openapi.json、/api/docs）
13. 监控端点（/monitor/health、/metrics、/info）
14. 网络连通性诊断工具箱（Ping / Traceroute / 端口探测 / DNS / 一键诊断）
15. 群晖 NAS 用户扫描与批量改密（DSM Web API + 审计）

## V1.6 更新内容
- 新增群晖 NAS 用户管理模块（`/nas/users/`）
  - DSM Web API 登录，支持双重验证、HTTPS、自签名证书
  - 扫描全部本地用户，展示用户组、管理员、密码策略、上次改密、2FA
  - 单个 / 批量改密，支持密码策略校验、CSV 导出、审计日志
  - 改密前读取并原样回传用户属性，避免覆盖描述、邮箱、过期时间等
  - 管理员账号二次确认，当前登录账号自动跳过
  - DSM 会话仅保存在进程内存，密码与 SID 不落库、不写日志
- 新增 `tools/nas_users_cli.py` 命令行工具（list / reset / dry-run / CSV）
- 新增 `tests/test_synology_users.py`（53 个）和 `tests/test_synology_script.py`（12 个）自动化测试
- 补齐 `requirements.txt` 完整依赖
- Web 界面升级至 V1.6

## V1.5 更新内容
- 深信服科技风格 UI 全面改版
  - 深蓝渐变侧边栏（#0a1628 → #0c2d6b）
  - 科技蓝主色调 #1677ff、青色强调 #00d4ff
  - 18 个模板文件统一风格
- IP 扫描记录支持删除操作
- IP 扫描记录支持分页显示（10/20/50 条每页）
- 新增网络连通性诊断工具箱
  - 5 个诊断工具：Ping、Traceroute、端口探测、DNS、一键诊断
  - 命令注入防护、输入校验、Windows 适配
  - 61 个自动化测试用例
- 新增项目 README 文档

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
