# 运维管理系统 - 长期记忆

## 项目概况
- 项目名称：运维管理系统 (Ops Manager)
- 当前版本：V1.3
- 技术栈：Python Flask + SQLAlchemy + SQLite + Bootstrap 5 + Chart.js
- 项目路径：C:\Users\22706\AppData\Roaming\Tencent\Marvis\User\oAN1i2aU4E_KYnCUugqzcgwbhcyQ\workspace\conv_19e54247999_cbf34ffe0703\output\ops_manager

## ⚠️ 文件输出规范（用户明确要求）
**所有团队输出的文件只能放到 `.workbuddy` 文件夹下，禁止输出到项目根目录或其他位置。**
分类结构：
```
.workbuddy/
├── memory/          # 工作记忆（已有）
├── docs/
│   ├── architecture/  # 架构相关文档
│   ├── prd/           # 产品需求文档
│   └── integration/   # 第三方集成方案
└── deliverables/      # 交付物（代码、报告等）
```
- 禁止在项目根目录下创建 docs/、overview.md 等文件
- 禁止将团队产出（PRD、架构文档、集成方案等）放到项目源码目录

## V1.3 已有功能
10个功能模块：攻击事件管理、配置变更管理、桌面运维工单、设备台账、快捷导航、IP存活扫描、中控大屏、首页概览、周报月报、安全事件中心

## V2.0 需求规划（2026-05-24 产品经理许清楚提出）
10个新需求，按优先级：
- P0: 用户认证与权限控制、操作审计日志、API体系完善
- P1: 告警通知与消息推送、自动巡检与定时任务、趋势分析与对比报表、批量操作与数据导入导出、工单流转与审批流程
- P2: SLA监控与仪表盘、全局搜索与高级筛选增强

## 架构审查（2026-05-24 架构师高见远）
- P0问题7个：to_dict()未实现、API参数签名不匹配、SECRET_KEY硬编码、无认证、requirements.txt不完整、Flask开发服务器、路由层穿透
- P1问题13个：IP扫描代码重复、缺索引、N+1查询、零测试等
- 三阶段路线图：基础加固→认证+PG→定时任务+Webhook

## 第三方集成规划
- 用户需要集成 Zabbix 和深信服 AF

## 已知技术债务（架构审查更新）
- API层to_dict()未实现（运行时AttributeError）
- API参数与Service签名不匹配（运行时TypeError）
- API端点不完整（仅attacks和configs有RESTful API）
- SECRET_KEY硬编码回退值
- 日志模块logging_config.py未被调用
- IP扫描服务层与路由层代码重复
- 无用户认证机制
- requirements.txt不完整（缺requests/feedparser/openpyxl/psutil）
- Flask开发服务器跑生产
- 路由层穿透（main/quick_access/monitor直接操作ORM）
- 零测试覆盖率
- 无数据库Migration
