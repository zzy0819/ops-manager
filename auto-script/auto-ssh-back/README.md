# 华三交换机配置批量备份工具（auto-ssh-back）

## 简介

本工具用于**批量 SSH 登录华三（H3C / Comware）交换机并保存运行配置**，可选在保存前先把当前运行配置备份到本地 `.cfg` 文件。适用于定期巡检、批量下发 `save` 命令、变更前配置备份等运维场景。

配套 `ssh_probe.py` 用于**探测设备 SSH 算法清单**，定位无法登录（算法协商失败）的原因——不需要账号密码，也不会登录设备。

## 环境依赖

```bash
pip install netmiko openpyxl paramiko
```

- Python 3.7+（脚本使用了 `from __future__ import annotations`）
- 运行环境需网络可达目标设备的 SSH 端口

## 设备清单（Excel）

以 `devices_template.xlsx` 为模板，第一行为表头，表头支持中英文列名，必需三列：

| 列名 | 含义 | 必填 | 说明 |
|------|------|------|------|
| IP | 管理 IP 或域名 | 是 | 支持 IPv4 与域名 |
| 用户名 | SSH 登录用户名 | 是 | |
| 密码 | 登录密码 | 是 | 纯数字请把单元格设为「文本」，避免前导 0 被吃掉 |
| 端口 | SSH 端口 | 否 | 默认 22，范围 1–65535 |
| 设备名称 | 设备名 | 否 | 缺省用 IP；用于报告与备份文件名 |
| super密码 | super 提权密码 | 否 | 需要提权时才填 |

> 支持多行设备；完全空行自动跳过；`IP + 端口` 重复会被判定为重复项并跳过。

生成模板：

```bash
python h3c_batch_save.py --template
```

## 使用方法

```bash
# 仅校验端口 + 账号密码，不保存（dry run）
python h3c_batch_save.py -f devices.xlsx --check-only

# 校验通过后保存配置（save force）
python h3c_batch_save.py -f devices.xlsx

# 先备份当前配置到 ./backup，再保存
python h3c_batch_save.py -f devices.xlsx --backup

# 自定义并发 / 超时 / 重试
python h3c_batch_save.py -f devices.xlsx -w 10 -t 15 -r 2

# 启动时直接启用旧版 SSH 算法（默认遇到协商失败才自动启用）
python h3c_batch_save.py -f devices.xlsx --legacy-ssh

# 调试模式（输出详细日志）
python h3c_batch_save.py -f devices.xlsx -v
```

参数说明：

| 参数 | 含义 | 默认值 / 范围 |
|------|------|------|
| `-f/--file` | 设备清单 Excel | 必填（除非 `--template`） |
| `-w/--workers` | 并发数 | 1–50，默认 5 |
| `-t/--timeout` | 连接 / 认证超时（秒） | ≥3，默认 20 |
| `-r/--retries` | 网络类错误重试次数 | 0–5，默认 2（**认证失败不重试**） |
| `--check-only` | 只校验不保存 | |
| `--backup [DIR]` | 先备份当前配置 | 目录默认 `./backup` |
| `--legacy-ssh` | 启动即启用旧算法 | |
| `--template` | 生成模板并退出 | |
| `-v/--verbose` | 调试日志 | |

## 处理流程（每台设备）

1. **参数校验**：IP/域名合法性、端口范围、账号密码非空、重复项检测
2. **端口检测**：TCP 连通性 + 读取 SSH banner 确认为 SSH 服务；连接被拒绝、域名解析失败**不重试**
3. **登录认证**：netmiko `hp_comware` 驱动；认证失败立即失败（防账号锁定），仅网络类错误才按次数重试
4. **登录后校验**：识别 `<SW>` / `[SW]` 提示符，确认是 Comware 设备；位于系统视图时自动 `return` 退回用户视图
5. **保存配置**：`save force`，按回显关键词判定成功 / 失败 / 未确认，自动应答 `[Y/N]` 与文件名确认

## 报告与日志

- 每次运行生成 `save_config_YYYYMMDD_HHMMSS.log`（同时输出控制台与文件，paramiko 噪音已屏蔽）
- 生成 `save_config_result_YYYYMMDD_HHMMSS.xlsx` 报告，字段：行号 / 设备名 / IP / 端口 / 提示符 / 结果 / 失败阶段 / 详情 / 耗时
- 若 Excel 写入失败（文件被占用 / 无权限），自动降级为 CSV（utf-8-sig）

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 全部成功 |
| 1 | 存在失败 / 未确认 / 跳过 |
| 130 | 用户中断（Ctrl+C） |

## 老设备 SSH 兼容（重要）

部分老设备（如 Comware 5）只支持 SHA-1 类密钥交换与 `ssh-rsa` / `ssh-dss`，而新版本 paramiko（≥5）已移除这些算法，会导致 "算法协商失败"。

- 脚本检测到协商失败时会**自动启用旧算法**（仅追加到列表末尾，不影响新设备优先协商强算法）
- 若本机 paramiko ≥5 且旧算法已移除，会提示降级：

  ```bash
  pip install "paramiko<5"
  ```

- 也可先用 `ssh_probe.py` 探测设备支持的算法清单，并与本机 paramiko 对比：

  ```bash
  python ssh_probe.py 10.12.10.10
  python ssh_probe.py 10.12.10.10 -p 22 -t 10
  ```

## 安全注意事项

- 设备清单 Excel 含明文密码，请妥善保管，避免提交到版本库
- 认证失败**不会重试**，以避免触发设备账号锁定策略
- `--backup` 会写入设备完整运行配置，注意备份目录的存储权限

## 文件清单

| 文件 | 说明 |
|------|------|
| `h3c_batch_save.py` | 主脚本：批量登录并保存配置 |
| `ssh_probe.py` | SSH 算法探测工具（无需账号密码） |
| `devices_template.xlsx` | 设备清单模板（由 `--template` 生成或随包提供） |
