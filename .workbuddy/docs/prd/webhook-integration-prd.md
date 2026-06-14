# Webhook 与第三方集成 — 详细需求文档

> **项目**: 运维管理系统 V2.0  
> **模块**: Webhook 与第三方集成  
> **版本**: PRD v1.0  
> **作者**: 许清楚（Xu）· 产品经理  
> **日期**: 2026-05-24

---

## 1. 需求背景与价值

### 1.1 现状痛点

当前运维管理系统 V1.3 是一个**信息孤岛**——攻击事件、配置变更、工单、设备台账等数据全部封闭在系统内部，运维人员必须**主动登录系统**才能获知变化。这带来以下具体问题：

| 痛点 | 具体表现 | 影响 |
|------|----------|------|
| **被动响应** | 安全事件发生后，运维人员无即时感知，依赖人工巡检或周期性登录查看 | 响应延迟，小事件演变为大事故 |
| **工具割裂** | 运维团队日常使用钉钉/飞书/企业微信沟通，但系统无法将事件推送到这些工具 | 信息在多平台间手动搬运，效率低 |
| **自动化断链** | 配置变更、设备上下线等事件无法自动触发下游流程（如自动更新 CMDB、触发巡检脚本） | 依赖人工衔接，易遗漏 |
| **审计追踪困难** | 第三方系统对运维管理系统的操作无回调记录，无法形成完整审计链 | 合规风险 |
| **重复录入** | 同一事件需在多个系统中重复登记 | 人力浪费，数据不一致 |

### 1.2 核心价值

1. **实时触达**：关键事件秒级推送到钉钉/飞书/企业微信/邮件等渠道，变被动查看为主动通知
2. **流程自动化**：事件驱动的自动化编排，减少人工衔接环节
3. **生态互联**：与 Zabbix、Jenkins、CMDB、SOAR 等运维工具形成事件联动闭环
4. **审计闭环**：双向 Webhook 实现操作可追溯

---

## 2. 核心功能清单

### P0 — 必须实现

| 编号 | 功能 | 说明 |
|------|------|------|
| F-01 | Webhook 出站推送 | 系统事件发生时，主动向外部 URL 发送 HTTP POST 通知 |
| F-02 | Webhook 配置管理 | 创建、编辑、删除、启用/禁用 Webhook 端点 |
| F-03 | 事件类型订阅 | 每个 Webhook 可选择性订阅一个或多个事件类型 |
| F-04 | 签名验证 | 出站请求携带 HMAC-SHA256 签名，接收方可验证真实性 |
| F-05 | 推送日志 | 记录每次推送的请求/响应详情，支持查询与排查 |
| F-06 | 失败重试 | 推送失败后按指数退避策略自动重试 |
| F-07 | 手动测试 | 创建/编辑 Webhook 后可发送测试事件验证连通性 |
| F-08 | 预置集成模板 | 提供钉钉机器人、飞书机器人、企业微信机器人的开箱即用模板 |

### P1 — 应当实现

| 编号 | 功能 | 说明 |
|------|------|------|
| F-09 | 自定义请求头 | 每个 Webhook 可配置最多 10 个自定义 HTTP Header |
| F-10 | 自定义 Payload 模板 | 支持使用变量模板自定义推送数据格式，适配不同第三方 API |
| F-11 | Secret 加密存储 | Webhook Secret 在数据库中加密存储，界面脱敏显示 |
| F-12 | 推送统计仪表盘 | 展示各 Webhook 的成功率、延迟、近 N 天趋势 |
| F-13 | 事件过滤 | 支持按事件属性过滤（如仅推送 P0/P1 级别的攻击事件） |
| F-14 | 外部 Webhook 接收 | 提供统一回调端点，接收外部系统的事件推送 |
| F-15 | IP 白名单 | 限制出站 Webhook 仅推送到指定 IP 段，入站仅接受白名单 IP 的回调 |

### P2 — 锦上添花

| 编号 | 功能 | 说明 |
|------|------|------|
| F-16 | 死信队列与事件重放 | 重试耗尽的事件进入死信队列，支持手动重放 |
| F-17 | 批量导入/导出 Webhook 配置 | 便于环境迁移和配置备份 |
| F-18 | Webhook 调用频率限制 | 防止事件风暴冲击下游系统 |
| F-19 | 自定义响应判定规则 | 默认 2xx 为成功，可自定义判定逻辑 |
| F-20 | 集成市场 | 提供更多预置模板（Slack、Teams、PagerDuty 等） |

---

## 3. 事件类型定义

### 3.1 事件类型总表

| 事件代码 | 事件名称 | 所属模块 | 触发时机 | 优先级 |
|----------|----------|----------|----------|--------|
| `attack_event.created` | 攻击事件创建 | 攻击事件管理 | 新建攻击事件时 | P0 |
| `attack_event.updated` | 攻击事件更新 | 攻击事件管理 | 攻击事件字段变更时 | P0 |
| `attack_event.deleted` | 攻击事件删除 | 攻击事件管理 | 删除攻击事件时 | P1 |
| `attack_event.escalated` | 攻击事件升级 | 攻击事件管理 | 事件严重级别被提升时 | P0 |
| `config_change.created` | 配置变更创建 | 配置变更管理 | 新建配置变更记录时 | P0 |
| `config_change.updated` | 配置变更更新 | 配置变更管理 | 变更记录状态变更时 | P0 |
| `config_change.approved` | 配置变更审批通过 | 配置变更管理 | 变更审批通过时 | P0 |
| `config_change.rejected` | 配置变更审批驳回 | 配置变更管理 | 变更审批驳回时 | P1 |
| `work_order.created` | 工单创建 | 桌面运维工单 | 新建工单时 | P0 |
| `work_order.assigned` | 工单分配 | 桌面运维工单 | 工单被分配给处理人时 | P0 |
| `work_order.resolved` | 工单解决 | 桌面运维工单 | 工单状态变为已解决时 | P0 |
| `work_order.closed` | 工单关闭 | 桌面运维工单 | 工单被关闭时 | P1 |
| `work_order.overdue` | 工单逾期 | 桌面运维工单 | 工单超过 SLA 未解决时 | P0 |
| `device.registered` | 设备入账 | 设备台账管理 | 新设备登记入台账时 | P1 |
| `device.updated` | 设备信息更新 | 设备台账管理 | 设备信息变更时 | P1 |
| `device.offline` | 设备离线 | IP 存活扫描 | 扫描发现设备离线时 | P0 |
| `device.online` | 设备上线 | IP 存活扫描 | 扫描发现设备重新上线时 | P1 |
| `ip_scan.completed` | 扫描完成 | IP 存活扫描 | 一次 IP 存活扫描完成时 | P1 |
| `report.generated` | 报告生成 | 周报/月报 | 周报/月报自动生成时 | P1 |
| `security_event.triggered` | 安全事件触发 | 安全事件中心 | 安全事件规则命中时 | P0 |
| `webhook.delivery_failed` | 推送失败 | Webhook 系统 | Webhook 推送最终失败时 | P1 |

### 3.2 标准推送数据结构

所有出站 Webhook 推送遵循统一信封格式：

```json
{
  "event_id": "evt_a1b2c3d4e5f6",
  "event_type": "attack_event.created",
  "event_time": "2026-05-24T14:30:00+08:00",
  "source": "ops-management-system",
  "source_version": "2.0.0",
  "data": {},
  "operator": {
    "id": 1,
    "username": "admin",
    "display_name": "系统管理员"
  }
}
```

---

## 4. Webhook 配置管理

### 4.1 配置界面

Webhook 管理入口位于系统设置 → 集成管理 → Webhook，提供列表视图和表单视图。

#### 创建/编辑表单

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| 名称 | 文本 | 是 | Webhook 标识名 |
| 描述 | 文本区 | 否 | 用途说明 |
| 推送 URL | URL | 是 | 接收推送的 HTTPS 端点 |
| Secret | 密码 | 否 | 用于签名验证的密钥，自动生成或手动输入 |
| 事件订阅 | 多选 | 是 | 至少选择一个事件类型 |
| 事件过滤规则 | JSON 编辑器 | 否 | 按事件属性过滤 |
| 自定义请求头 | 键值对 | 否 | 最多 10 组 Key:Value |
| Payload 模板 | 代码编辑器 | 否 | 自定义推送格式模板 |
| 启用状态 | 开关 | 是 | 默认启用 |
| SSL 验证 | 开关 | 否 | 是否验证目标服务器 SSL 证书，默认启用 |

### 4.2 预置集成模板

| 模板名称 | 目标平台 | 自动配置内容 |
|----------|----------|-------------|
| 钉钉机器人 | 钉钉 | 自定义请求头 + Payload 模板（适配钉钉 OpenAPI 格式） |
| 飞书机器人 | 飞书 | 自定义请求头 + Payload 模板（适配飞书 OpenAPI 格式） |
| 企业微信机器人 | 企业微信 | 自定义请求头 + Payload 模板（适配企微 Markdown 消息格式） |
| 通用 HTTP | 任意 | 标准 JSON 推送，无额外转换 |
| 邮件通知 | SMTP 网关 | 转换为邮件网关 API 格式 |

---

## 5. 安全机制

### 5.1 出站签名验证

遵循 [Standard Webhooks](https://www.standardwebhooks.com/) 规范。每个出站请求携带以下 Header：

| Header | 说明 | 示例 |
|--------|------|------|
| `webhook-id` | 事件唯一 ID（幂等键） | `evt_a1b2c3d4e5f6` |
| `webhook-timestamp` | 请求生成时的 Unix 时间戳 | `1744578123` |
| `webhook-signature` | HMAC-SHA256 签名 | `v1,base64_encoded_signature==` |
| `X-OpsMS-Event` | 事件类型名称 | `attack_event.created` |
| `X-OpsMS-Signature-256` | 兼容旧格式签名 | `sha256=abcdef123456` |

### 5.2 Secret 管理

| 安全措施 | 说明 |
|----------|------|
| 生成方式 | 创建 Webhook 时可手动指定或自动生成（32 字节随机 hex） |
| 存储方式 | 数据库中使用 AES-256-GCM 加密存储，解密密钥存放于环境变量 |
| 界面显示 | 仅创建时展示一次完整 Secret，之后以 `sk_****xxxx` 格式脱敏显示 |
| 传输安全 | 出站推送强制 HTTPS，配置时可选择是否验证 SSL 证书 |
| 轮换支持 | 支持重新生成 Secret，更新后旧签名立即失效 |

---

## 6. 可靠性设计

### 6.1 异步推送架构

```
事件发生 → 写入事件队列 → Worker 异步消费 → HTTP POST 推送 → 记录日志
```

### 6.2 重试策略

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 最大重试次数 | 5 | 超过此次数进入死信队列 |
| 退避策略 | 指数退避 + 抖动 | 避免重试风暴 |
| 重试间隔 | 1s, 2s, 4s, 8s, 16s | 最多等待 16 秒 |
| 超时时间 | 10s | 单次 HTTP 请求超时 |
| 成功判定 | HTTP 2xx | 非 2xx 视为失败 |

### 6.3 自动禁用机制

| 条件 | 动作 |
|------|------|
| 连续失败 4 次 | 临时禁用，1 分钟后自动恢复 |
| 恢复后仍失败 | 禁用时间翻倍（2min → 4min → ... → 24h 上限），之后自动恢复 |
| 连续失败 40 次 | 永久禁用，需手动重新启用 |
| 手动测试成功 | 重置失败计数，重新启用 |

---

## 7. 外部 Webhook 接收

### 7.1 统一回调端点

```
POST /api/v1/webhooks/incoming/{channel_id}
```

### 7.2 支持的入站场景

| 场景 | 来源系统 | 触发动作 |
|------|----------|----------|
| Zabbix 告警回调 | Zabbix | 自动创建攻击事件 |
| Jenkins 构建通知 | Jenkins | 更新配置变更状态 |
| CMDB 同步回调 | 外部 CMDB | 更新设备台账信息 |
| 安全扫描器回调 | Nessus/OpenVAS | 创建攻击事件 |
| 审批系统回调 | OA/审批系统 | 更新配置变更审批状态 |

---

## 8. 典型集成场景

1. **攻击事件钉钉告警**：安全事件触发 → 钉钉群告警卡片
2. **配置变更审批后触发 Jenkins 部署**：审批通过 → Jenkins Pipeline
3. **设备离线飞书告警 + 自动创建工单**：扫描发现离线 → 告警+工单
4. **Zabbix 告警自动录入攻击事件**：入站 Webhook 接收外部告警
5. **周报生成后企微通知 + 邮件分发**：定时生成后多渠道推送
6. **工单逾期多级升级通知**：处理人→主管→部门负责人逐级告警

---

## 9. 数据模型设计建议

### 9.1 webhooks — Webhook 配置表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 主键 |
| name | VARCHAR(100) | NOT NULL | Webhook 名称 |
| description | TEXT | | 描述 |
| url | VARCHAR(500) | NOT NULL | 推送目标 URL |
| secret_encrypted | VARCHAR(500) | | AES 加密后的 Secret |
| secret_hash | VARCHAR(64) | | Secret 的 SHA-256 哈希 |
| is_active | BOOLEAN | DEFAULT 1 | 是否启用 |
| is_auto_disabled | BOOLEAN | DEFAULT 0 | 是否被自动禁用 |
| consecutive_failures | INTEGER | DEFAULT 0 | 连续失败次数 |
| auto_disable_until | DATETIME | | 临时禁用截止时间 |
| ssl_verify | BOOLEAN | DEFAULT 1 | 是否验证 SSL |
| custom_headers | JSON | | 自定义请求头 |
| payload_template | TEXT | | 自定义 Payload 模板 |
| allowed_target_cidrs | VARCHAR(500) | | 出站 IP 白名单 |
| rate_limit_per_min | INTEGER | DEFAULT 60 | 每分钟推送限制 |
| timeout_seconds | INTEGER | DEFAULT 10 | 请求超时秒数 |
| max_retries | INTEGER | DEFAULT 5 | 最大重试次数 |
| preset_template | VARCHAR(50) | | 预置模板标识 |
| created_by | INTEGER | FK → users.id | 创建人 |
| created_at | DATETIME | DEFAULT NOW | 创建时间 |
| updated_at | DATETIME | | 更新时间 |

### 9.2 webhook_events — Webhook 事件订阅表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 主键 |
| webhook_id | INTEGER | FK → webhooks.id | 关联 Webhook |
| event_type | VARCHAR(50) | NOT NULL | 事件类型代码 |
| filter_rules | JSON | | 事件过滤规则 |
| UNIQUE | | (webhook_id, event_type) | 联合唯一 |

### 9.3 webhook_delivery_logs — 推送日志表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 主键 |
| webhook_id | INTEGER | FK → webhooks.id | 关联 Webhook |
| event_id | VARCHAR(50) | NOT NULL | 事件唯一 ID |
| event_type | VARCHAR(50) | NOT NULL | 事件类型 |
| attempt | INTEGER | DEFAULT 1 | 第几次尝试 |
| is_test | BOOLEAN | DEFAULT 0 | 是否测试推送 |
| request_url | VARCHAR(500) | | 请求 URL |
| request_headers | TEXT | | 请求头 |
| request_body | TEXT | | 请求体 |
| response_status_code | INTEGER | | HTTP 响应状态码 |
| response_body | TEXT | | 响应体（截断至 4KB） |
| duration_ms | INTEGER | | 耗时毫秒 |
| status | VARCHAR(20) | NOT NULL | pending / success / failed |
| error_message | TEXT | | 错误信息 |
| next_retry_at | DATETIME | | 下次重试时间 |
| created_at | DATETIME | DEFAULT NOW | 创建时间 |

### 9.4 webhook_incoming_channels — 入站通道表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 主键 |
| channel_id | VARCHAR(50) | UNIQUE, NOT NULL | 通道唯一标识 |
| name | VARCHAR(100) | NOT NULL | 通道名称 |
| description | TEXT | | 描述 |
| auth_type | VARCHAR(20) | NOT NULL | 鉴权方式 |
| auth_config | JSON | | 鉴权配置 |
| allowed_source_ips | VARCHAR(500) | | 入站 IP 白名单 |
| target_module | VARCHAR(50) | NOT NULL | 路由目标模块 |
| action_config | JSON | | 执行动作配置 |
| is_active | BOOLEAN | DEFAULT 1 | 是否启用 |
| created_by | INTEGER | FK → users.id | 创建人 |
| created_at | DATETIME | DEFAULT NOW | 创建时间 |
| updated_at | DATETIME | | 更新时间 |

### 9.5 webhook_dead_letters — 死信表（P2）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 主键 |
| webhook_id | INTEGER | FK → webhooks.id | 关联 Webhook |
| event_id | VARCHAR(50) | NOT NULL | 事件 ID |
| event_type | VARCHAR(50) | NOT NULL | 事件类型 |
| last_attempt_log_id | INTEGER | FK → webhook_delivery_logs.id | 最后一次推送日志 |
| failure_reason | TEXT | | 最终失败原因 |
| retry_count | INTEGER | | 已重试次数 |
| payload | TEXT | | 原始推送内容 |
| status | VARCHAR(20) | DEFAULT 'pending' | pending / replayed / discarded |
| created_at | DATETIME | DEFAULT NOW | 进入死信时间 |
| resolved_at | DATETIME | | 重放/丢弃时间 |

---

## 10. 验收标准

### P0 验收标准
1. 创建 Webhook 后，订阅的事件发生时系统在 3 秒内发出 HTTP POST 请求
2. 推送请求携带 Standard Webhooks 规范 Header
3. 使用正确的 Secret 可成功验证签名
4. 推送失败后按指数退避策略自动重试，最多 5 次
5. 每次推送（含重试）在推送日志中有完整记录
6. 预置钉钉/飞书/企微模板选择后，填写必要参数即可推送成功
7. 出站推送强制 HTTPS
8. Secret 创建后仅在界面展示一次

### P1 验收标准
9. 自定义 Payload 模板中的变量正确替换为事件数据
10. 事件过滤规则生效，仅推送符合条件的事件
11. 入站 Webhook 端点可接收 POST 请求并正确路由
12. 连续失败 40 次后 Webhook 被自动禁用
13. Secret 在数据库中加密存储，界面脱敏显示

---

## 11. 技术实现建议

初期使用 APScheduler + SQLite 队列表做后台推送 Worker（不引入 Redis），后续按需升级到 RQ。

推送并发控制：ThreadPoolExecutor，默认最大并发 10，每个 Webhook 串行推送（保证顺序），不同 Webhook 间并行。

---

## 附录：MVP 版本范围

**V2.0 MVP 阶段实现范围**（P0 功能）：
1. Webhook 出站推送（F-01）
2. Webhook CRUD 配置管理（F-02）
3. 事件类型订阅（F-03），先支持 6 个核心事件类型
4. HMAC-SHA256 签名验证（F-04）
5. 推送日志（F-05）
6. 失败重试（F-06）
7. 手动测试（F-07）
8. 钉钉/飞书/企微预置模板（F-08）
