# h3c-ops-agent

华三（H3C / Comware V5·V7）交换机批量运维 Agent：**巡检 → 配标准团体名 → 接入 Zabbix → 备份配置**，一条命令跑完，输出 Excel + Markdown 报告。

面向"一次性把几十台交换机纳入监控"的场景：不用逐台登进去敲 `snmp-agent`，也不用在 Zabbix 里手点添加主机。

---

## 先说重点

**默认是预览模式，不改任何设备。** 加 `--apply` 才会真正下发配置、写 Zabbix、`save` 落盘。

```bash
python run.py init                    # 生成 config.json + devices.xlsx
# 编辑这两个文件（设备清单、账号、团体名、Zabbix 地址）
python run.py devices                 # 确认清单解析正确
python run.py inspect                 # 只读巡检，先看看设备状态
python run.py full                    # 预览：巡检+团体名+Zabbix+备份，不落任何变更
python run.py full --apply            # 实际执行（会二次确认）
```

**只想配团体名**，设备清单里填好 IP / 用户名 / 密码，两条命令就够：

```bash
python run.py snmp                    # 预览：打印用哪个账号、配什么团体名、ACL 放行谁
python run.py snmp --apply -y         # 批量登录 → 下发 → 回读校验 → save
```

四个阶段都做了**幂等**处理：已符合标准的设备会显示"无变化"，重复跑不会反复改设备。

---

## 能力清单

| 阶段 | 做什么 | 是否改设备 |
|------|--------|-----------|
| `inspect` 巡检 | 型号/序列号/Comware 版本/运行时长、CPU、内存、温度、风扇、电源、端口 up-down、光模块收光、SNMP 配置现状，输出健康分与告警 | 只读 |
| `snmp` 团体名 | 按清单账号密码登录（失败自动换候选账号）、必要时 `super` 提权，统一 v2c + 只读团体名 + **ACL 只放行监控平台 IP** + trap 指向 Zabbix；不配写团体名；下发后回读校验 | 改（需 `--apply`） |
| `zabbix` 接入 | 建主机组、关联华三模板、建 SNMP 接口、写 `{$SNMP_COMMUNITY}` 宏、启用监控 | 改 Zabbix（需 `--apply`） |
| `backup` 备份 | `display current-configuration` 快照 + `latest.cfg` + 与上一版的 unified diff + 按份数保留 | 改（`save` 需 `--apply`） |

健康判定阈值可调（默认 CPU>80%、内存>85%、温度>60℃、任一物理口 down、风扇/电源异常）。

---

## 快速开始

### 1. 装依赖

```bash
pip install -r requirements.txt      # paramiko / requests / openpyxl
```

### 2. 初始化

```bash
python run.py init
```

生成：

- `config.json` —— 全局配置（从 `config.example.json` 复制）
- `devices.xlsx` —— 设备清单模板

### 3. 填设备清单

`devices.xlsx`（也支持 `.csv` / `.json`），列名中英文均可：

| 列 | 必填 | 说明 |
|----|------|------|
| 设备名称 | 否 | 留空则用 IP；Zabbix 主机名优先取设备 `sysname` |
| IP | **是** | 管理地址，支持域名 |
| 用户名 / 密码 | 否 | 留空则用 `config.json` 的默认凭据 |
| 端口 | 否 | 默认 22 |
| super密码 | 否 | 账号权限不足时填，登录后自动 `super` 提权 |
| 分组 | 否 | 覆盖 Zabbix 主机组，如 `核心区` |
| Zabbix模板 | 否 | 覆盖模板名（按设备型号不同时用） |
| 团体名 | 否 | 覆盖全局团体名（个别设备要特殊值时用） |
| 位置 | 否 | 覆盖 SNMP location |
| 备注 / 启用 | 否 | 启用填"否"则跳过该行 |

> 密码列为纯数字时，请把单元格格式设为"文本"，否则 Excel 会吃掉前导 0。

用 `python run.py devices` 可以看到每台设备**实际会用哪个账号登录**（来源标记为"设备清单"还是"配置默认"）和密码位数，填错了当场能看出来。

### 3.1 账号密码怎么给（自动登录规则）

按下面的顺序取，取到能登录的为止：

1. 命令行 `--user` / `--password` —— **只用它**，不再回落到清单（避免"以为在试 A，其实试了 B"）
2. **设备清单该行的用户名 / 密码**
3. `config.json` → `credentials.candidates` 候选账号（可配多套，如 `admin`、`h3c`）
4. `config.json` → `credentials.username` / `password`（兜底）

```jsonc
"credentials": {
  "username": "netops", "password": "默认密码", "secret": "",
  "candidates": [
    { "username": "admin", "password": "Admin@123" },
    { "username": "h3c",   "password": "H3C@1234", "secret": "super密码" }
  ]
}
```

规则细节：

- **同一个账号密码只试一次**。认证失败才换下一个账号，绝不重复试同一个——避免触发设备账号锁定。
- **网络类错误不换账号**（超时、算法协商失败、提示符识别失败），换账号没有意义，直接报错。
- 用了备用账号会记进报告的「需要注意」里，不会悄悄换成别的账号。
- 配了 `super密码` 时登录后自动提权；提权失败只记告警，继续尝试（真进不去 `system-view` 会明确报"账号权限不足"）。

### 3.2 登录不上时的对照表

| 现象 | 原因 | 处理 |
|------|------|------|
| 认证失败 | 账号密码错 / 账号无 SSH 权限 | 核对清单；已自动尝试候选账号，仍失败会列出试过哪些 |
| 连接超时 | 路由、ACL、防火墙、SSH 未开 | 从本机 `telnet IP 22` 先确认端口通 |
| SSH 算法协商失败 | 老固件只支持 SHA-1 系算法，新版 paramiko 已移除 | 升级固件或在设备上放开兼容算法；实在不行用 `pip install "paramiko<3"` 的旧版环境 |
| 无法进入系统视图 | 账号权限低于 level 3 | 清单里补 `super密码`，或换有权限的账号 |
| 登录后无提示符 | 不是华三设备 / 登录后有多余交互（如首次改密） | 先手工登录一次确认 |

### 4. 改配置

`config.json` 里最少要改这几项：

```jsonc
{
  "credentials": { "username": "netops", "password": "你的密码" },
  "snmp": {
    "read_community": "OpsRead@2026",     // 至少 8 位，不能有空格
    "acl_sources": ["10.12.10.50"],       // Zabbix 服务器 IP，留空则不绑 ACL
    "trap_target": "10.12.10.50",
    "contact": "netops@example.com",
    "location": "DC-A"
  },
  "zabbix": {
    "url": "http://10.12.10.50",          // 不要带 /zabbix/api_jsonrpc.php
    "user": "Admin", "password": "zabbix",
    "host_group": "网络设备/华三交换机",
    "template_candidates": ["H3C Comware by SNMP"]
  }
}
```

密码也可以走环境变量，不落文件：`H3C_PASSWORD` / `ZABBIX_PASSWORD` / `ZABBIX_TOKEN`。

### 5. 跑

```bash
python run.py devices               # 清单自检
python run.py inspect --limit 2     # 先拿两台试巡检
python run.py full                  # 全流程预览
python run.py full --apply          # 正式执行
```

---

## 命令

```bash
python run.py <命令> [选项]
```

| 命令 | 说明 |
|------|------|
| `init` | 生成 `config.json` 与 `devices.xlsx` 模板 |
| `devices` | 只解析清单，打印有效/被拒绝的行（不连设备） |
| `inspect` | 只巡检 |
| `snmp` | 只配团体名 |
| `zabbix` | 只做 Zabbix 接入 |
| `backup` | 只备份配置 |
| `full` | 四个阶段全跑（默认命令） |

常用选项：

| 选项 | 说明 |
|------|------|
| `--apply` | 实际执行写操作（不加则只预览） |
| `-y` | 跳过交互确认（无人值守/定时任务用） |
| `--only 10.12.20.1` | 只处理指定设备，可重复；支持名称片段 |
| `--limit N` | 只处理前 N 台 |
| `-w N` | 并发数（1-50，默认 8） |
| `-f devices.xlsx` | 指定清单，覆盖配置 |
| `-c other.json` | 指定配置文件 |
| `--user` / `--password` | 临时指定账号密码（覆盖清单，两个必须同时给） |
| `--secret` | 临时指定 super 密码（配合 `--user`） |
| `-v` | 调试日志 |

示例：

```bash
# 按清单里的账号密码，批量配置团体名并保存
python run.py snmp --apply -y

# 先拿一台试水，确认巡检/团体名数据都对
python run.py snmp --apply -y --limit 1

# 临时用另一个账号（清单里的密码过期时应急）
python run.py snmp --apply -y --user admin --password 'Admin@123'

# 只给一台设备配团体名
python run.py snmp --only SW-Core-01 --apply -y

# 只看 Zabbix 接入计划，不写入
python run.py zabbix

# 巡检 5 台，单独的清单
python run.py inspect -f 新到货.xlsx --limit 5
```

### 定时跑（每日备份 / 每周巡检）

加 `-y` 即可无人值守。Windows 用「任务计划程序」、Linux 用 cron：

```bash
# 每天 02:00 备份配置 + 巡检
0 2 * * * cd /opt/ops-manager/h3c-ops-agent && /usr/bin/python3 run.py full --apply -y >> cron.log 2>&1
```

```powershell
# Windows：每天 02:00
schtasks /create /tn "h3c-ops-daily" /tr "D:\ops-manager\.venv\Scripts\python.exe D:\ops-manager\h3c-ops-agent\run.py full --apply -y" /sc daily /st 02:00
```

退出码：`0` 全部正常，`1` 存在失败（设备不可达 / 团体名失败 / Zabbix 冲突），`2` 配置或参数问题，`130` 用户中断。定时任务按退出码做告警即可。

---

## 产物

每次运行生成一个目录：

```
runs/20261029_2230/
├── report.xlsx      # 巡检汇总 / 问题明细 / 执行结果 / 运行信息
├── summary.md       # 摘要，先说结论
├── results.json     # 结构化结果（便于二次处理）
└── run.log          # 完整日志
```

配置备份：

```
backups/SW-Core-01/
├── 20261029_223045.cfg          # 每次快照
├── 20261029_223045.diff         # 与上一版的差异（有变化才生成）
├── 20261029_223045.meta.json    # 型号/版本/序列号/行数变化
├── latest.cfg                   # 最新一份
```

保留份数由 `backup.keep` 控制（默认 30），`latest.cfg` 永不被清理。

---

## 安全设计

1. **默认只读**：任何写操作都要显式 `--apply`，且 `--apply` 时还会二次确认（`-y` 可跳过）。
2. **团体名只读**：不配读写权限团体名，`write_community` 默认留空。
3. **ACL 收敛**：团体名绑定基本 ACL，只放行 `acl_sources` 里的监控平台 IP，其他地址 SNMP 不可达。ACL 只补齐缺失规则，不动已有规则。
4. **同一账号不重复试**：认证失败会换下一个候选账号（每个账号只试一次），绝不重复试同一个，避免触发设备账号锁定；网络类错误直接报错不换账号。
5. **Zabbix 同名冲突不覆盖**：主机名已存在但 SNMP 接口 IP 不一致时直接报"冲突"跳过，防止把另一台设备改坏；确认无误会再开 `overwrite_interface`。
6. **配置可回溯**：每次备份留快照和 diff，命令下发前有 `--apply` 确认，出问题能看 diff 定位。
7. **凭据不落库**：`config.json`、`devices.xlsx`、`runs/`、`backups/` 都在 `.gitignore` 里；日志和报告只记账号名，不记密码。

---

## Zabbix 侧前置条件

- Zabbix 5.0+（API 用 JSON-RPC，6.4+ 支持 Bearer Token）
- 已导入**华三模板**（如 `H3C Comware by SNMP`），模板名要和 `template_candidates` 对上；找不到时程序会把 Zabbix 里含 "H3C" 的模板名列出来提示
- API 账号需要有**超级管理员**或对主机/主机组/模板有读写权限
- Zabbix Server 到交换机的 161/UDP 要通，交换机到 Zabbix 的 162/UDP 要通（要收 trap 的话）
- 主机组名按字面创建，`网络设备/华三交换机` 就是一个含斜杠的名字，不会真的建两级

---

## 排错

| 现象 | 原因 / 处理 |
|------|-------------|
| `全部凭据均认证失败（已尝试 N 个账号）` | 清单账号和候选账号都进不去。报告里会列出试过哪些账号；改密码后重跑 |
| `SSH 算法协商失败` | 老设备只支持 SHA-1 系 KEX，新版 paramiko 已移除该实现。升级固件，或改用 `pip install "paramiko<3"` 的兼容环境 |
| `登录后未识别到设备提示符` | 不是华三设备 / 登录后还有额外交互（如二次认证菜单）。先手工 SSH 看一遍 |
| 巡检里 `display fan 执行失败` 但不影响结论 | 部分型号没有该命令，属正常（风扇/电源/温度按可选命令处理） |
| `未找到模板 H3C Comware by SNMP` | 先在 Zabbix 导入模板，或把 `template_candidates` 改成实际模板名 |
| Zabbix 返回 `412` | Token 或账号失效；`api_token` 与账号密码别同时配错 |
| `同名主机的 SNMP 接口 IP 是 x.x.x.x` | 冲突保护。确认该主机确实要换成清单里的 IP，再开 `zabbix.overwrite_interface` |
| `ACL 2001 已存在` | 会提示"仅补齐缺失的放行规则"。若该 ACL 已作他用，改 `snmp.acl_number` 换一个号 |
| 团体名改完 Zabbix 采集不到 | 确认 `acl_sources` 里有 Zabbix Server（或 Proxy）的真实出站 IP；trap 目标同理 |

---

## 开发

```
h3c-ops-agent/
├── run.py                  # 入口
├── config.example.json     # 配置模板
├── h3c_ops/
│   ├── config.py           # 配置加载（JSON + 默认值 + 环境变量）
│   ├── inventory.py        # 设备清单（xlsx/csv/json）
│   ├── login.py            # 登录策略：多套凭据回落 + super 提权
│   ├── ssh.py              # Comware 交互层（paramiko，提示符/分页/save/提权交互）
│   ├── inspect.py          # 巡检采集与健康判定（解析器均为纯函数）
│   ├── snmp.py             # 标准团体名 + ACL
│   ├── zabbix.py           # Zabbix API 接入（先查后改，产出变更计划）
│   ├── backup.py           # 配置备份与 diff
│   ├── report.py           # 控制台 / Markdown / Excel
│   ├── models.py           # 结果模型
│   └── runner.py           # 并发调度
└── tests/                  # 117 个用例，全部不依赖真实设备
```

测试：

```bash
python -m unittest discover -s tests -t .
```

测试用什么保证的：巡检解析器喂真实 Comware 回显样本；SSH 层用假 channel 模拟设备（覆盖分页、`save force` 的 `[Y/N]` 与文件名确认、`[flash:/startup.cfg]` 不被误判为提示符、`super` 提权的密码交互）；登录策略用假会话验证"回落顺序 / 每个账号只试一次 / 网络错误不换账号"；Zabbix 层只测变更计划，不发网络请求。

---

## 已知限制

- 只支持 SSH 登录，不支持 telnet（telnet 明文传密码，不建议）
- 只做了 Comware 语法；华为 VRP / 思科 IOS 需要改 `snmp.py` 与 `ssh.py` 的提示符规则
- 巡检项以"能快速判断设备健康"为准，没做路由协议邻居、STP 拓扑这类深度采集
- 配置 diff 是与**上一次备份**比，不是与 `startup-configuration` 比；设备上没有可靠的配置比对命令
- 当前 paramiko 5.x **不再实现 SHA-1 系 KEX 与 `ssh-rsa`**，只支持这些算法的早期固件（部分 Comware V5）会报"算法协商失败"，需要升级固件或用 `paramiko<3` 的兼容环境
- 数据库/AD 等外部认证账号不在支持范围（需要交互式输入密码的设备用不了）
