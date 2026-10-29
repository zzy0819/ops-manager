# 华三交换机配置批量保存

批量 SSH 登录华三（H3C / Comware）交换机并保存配置的命令行脚本。

本目录是 `ops-manager` monorepo 的 **auto-ssh-backup** 子项目。

- 脚本：[`auto-ssh-back.py`](./auto-ssh-back.py)
- 依赖：`netmiko`、`openpyxl`

---

## 功能

- 从 Excel 读取设备清单（IP / 用户名 / 密码 / 端口 / 设备名称 / super 密码）
- 逐台检测 SSH 端口与 banner，确认是 SSH 服务后再登录
- 登录认证失败**不重试**，避免触发设备账号锁定；网络类错误才重试
- 识别 Comware 提示符、退回用户视图，执行 `save force` 保存配置
- 并发处理多台设备，输出 Excel / CSV 结果报告与运行日志

---

## 安装依赖

```bash
pip install -r requirements.txt
```

或手动安装：

```bash
pip install netmiko openpyxl
```

---

## Excel 清单格式

第一行为表头，中英文列名均可：

```
IP | 用户名 | 密码 | 端口(可选,默认22) | 设备名称(可选) | super密码(可选)
```

- `IP`：设备管理 IP 或域名
- `用户名` / `密码`：SSH 登录凭据
- `端口`：默认 22
- `设备名称`：可选，用于报告展示
- `super密码`：可选，提权密码

> 密码如果是纯数字，请把单元格设置为「文本」格式，否则 Excel 会丢失前导 0。

---

## 用法

```bash
# 生成 Excel 模板
python auto-ssh-back.py --template

# 只校验端口 + 账号密码，不保存配置
python auto-ssh-back.py -f devices.xlsx --check-only

# 校验通过后保存配置
python auto-ssh-back.py -f devices.xlsx

# 自定义并发数、超时、重试次数
python auto-ssh-back.py -f devices.xlsx -w 10 -t 15 -r 2
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `-f, --file` | 设备清单 Excel 文件 | 必填 |
| `-w, --workers` | 并发数（1-50） | 5 |
| `-t, --timeout` | 连接/认证超时秒数 | 20 |
| `-r, --retries` | 网络类错误重试次数（认证失败不重试） | 2 |
| `--check-only` | 只校验端口与账号密码，不保存配置 | 关闭 |
| `--template` | 生成 Excel 模板并退出 | 关闭 |
| `-v, --verbose` | 输出调试日志 | 关闭 |

---

## 处理流程（每台设备）

1. **参数校验**：IP/域名、端口范围、用户名密码非空、重复项
2. **端口检测**：TCP 连通性 + 读取 SSH banner，确认是 SSH 服务
3. **登录认证**：认证失败不重试，避免账号锁定；网络类错误才重试
4. **登录后校验**：识别提示符、退出系统视图、检查是否 Comware 设备
5. **保存配置**：执行 `save force`，根据回显判断成功 / 失败 / 无法确认

---

## 输出文件

| 文件 | 说明 |
|------|------|
| `save_config_<时间戳>.log` | 运行日志 |
| `save_config_result_<时间戳>.xlsx` | 结果报告（默认） |
| `save_config_result_<时间戳>.csv` | 结果报告（Excel 写失败时降级） |
| `devices_template.xlsx` | `--template` 生成的清单模板 |

结果报告字段：行号、设备名称、IP、端口、设备提示符、结果、失败阶段、详情、耗时。

---

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 全部成功 / 全部校验通过 |
| 1 | 存在失败、未确认或跳过 |
| 130 | 用户中断 |

---

## 限制与安全

- 仅支持华三 Comware 系设备（`device_type="hp_comware"`）。
- 凭据只存在于 Excel 清单与进程内存，脚本日志中不输出密码。
- 认证失败不自动重试，避免触发设备账号锁定。
- 执行保存配置前建议先运行 `--check-only` 校验连通性与凭据。
