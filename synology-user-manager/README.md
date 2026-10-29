# 群晖 NAS 用户扫描 / 批量改密脚本

单文件脚本：[`synology_user_manager.py`](./synology_user_manager.py)

只依赖 Python 3.8+ 标准库，**不需要 `pip install`**。通过 DSM 官方 Web API 工作，
不需要 SSH，也不需要 NAS 安装套件。

本目录是 `ops-manager` monorepo 的 **synology-user-manager** 子项目。

---

## 功能

- 通过 DSM Web API 登录（支持 HTTPS、自签名证书、双重验证）
- 扫描全部**本地用户**，显示用户组、管理员、密码策略、上次改密、2FA
- 按用户名列表或全部用户批量重置密码
- 改密前读取用户当前属性并原样回传，避免覆盖描述、邮箱、过期时间等
- 支持预演（`--dry-run`）、CSV 导出、可选审计日志

---

## 直接运行（交互模式）

```bash
python synology_user_manager.py
```

按提示输入 NAS 地址、管理员账号、密码，扫描完成后选择用户即可批量改密。

---

## 扫描用户

```bash
python synology_user_manager.py list --host 192.168.1.10 --account admin
```

导出 CSV：

```bash
python synology_user_manager.py list --host 192.168.1.10 --account admin --csv users.csv
```

输出 JSON：

```bash
python synology_user_manager.py list --host 192.168.1.10 --account admin --json
```

自签名证书加 `--insecure`；DSM 的 HTTP 端口通常是 5000：

```bash
python synology_user_manager.py list --host 192.168.1.10 --account admin --insecure
python synology_user_manager.py list --host 192.168.1.10 --port 5000 --http --account admin
```

---

## 批量修改密码

### 推荐：新密码从标准输入读取

```bash
# Linux / macOS
printf '%s\n' 'NewStr0ng!Pass' | python synology_user_manager.py reset \
  --host 192.168.1.10 --account admin --users alice,bob --new-password-stdin
```

```powershell
# Windows PowerShell
'NewStr0ng!Pass' | python synology_user_manager.py reset `
  --host 192.168.1.10 --account admin --users alice,bob --new-password-stdin
```

管理员密码交互式提示输入；也可用环境变量：

```powershell
$env:SYNOLOGY_PASSWORD = '管理员密码'
$env:SYNOLOGY_NEW_PASSWORD = 'NewStr0ng!Pass'
python synology_user_manager.py reset `
  --host 192.168.1.10 --account admin --users alice,bob --yes
```

### 预演（只校验，不修改）

```bash
printf '%s\n' 'NewStr0ng!Pass' | python synology_user_manager.py reset \
  --host 192.168.1.10 --account admin --users alice,bob --new-password-stdin --dry-run
```

### 全部用户

```bash
printf '%s\n' 'NewStr0ng!Pass' | python synology_user_manager.py reset \
  --host 192.168.1.10 --account admin --all --new-password-stdin
```

`--all` 自动排除 `guest` 账号和当前登录账号；管理员默认拒绝，必须显式加 `--allow-admin`。

### 重置管理员密码（高风险）

```bash
printf '%s\n' 'NewStr0ng!Pass' | python synology_user_manager.py reset \
  --host 192.168.1.10 --account admin --users backup_admin --new-password-stdin --allow-admin
```

### 审计日志

```bash
python synology_user_manager.py reset ... --audit-log reset-audit.csv
```

审计字段：时间、NAS、登录账号、目标用户、结果、说明。**不记录密码。**

---

## 参数说明

| 参数 | 说明 |
|------|------|
| `--host` | NAS 地址，支持 `192.168.1.10`、`nas.local`、`https://nas:5001` |
| `--port` | DSM 端口，默认 5001；HTTP 通常为 5000 |
| `--http` | 使用 HTTP（默认 HTTPS） |
| `--insecure` | 跳过 TLS 证书校验（自签名证书） |
| `--account` | DSM 管理员账号，必须属于 `administrators` 组 |
| `--otp` | 双重验证动态码 |
| `--password-env` | 管理员密码所在环境变量，默认 `SYNOLOGY_PASSWORD` |
| `--password-stdin` | 从标准输入读取管理员密码 |
| `--new-password-env` | 新密码所在环境变量，默认 `SYNOLOGY_NEW_PASSWORD` |
| `--new-password-stdin` | 从标准输入读取新密码 |
| `--users` | 逗号分隔的用户名 |
| `--all` | 全部本地用户（排除 guest 和当前账号） |
| `--allow-admin` | 允许重置管理员账号 |
| `--dry-run` | 只校验密码策略，不实际修改 |
| `--yes` | 跳过 `RESET` 确认（自动化慎用） |
| `--audit-log` | 审计 CSV 路径 |

---

## 安全设计

1. **不会覆盖用户属性**：DSM 的 `SYNO.Core.User.set` 是整体更新接口。脚本先 `get`
   用户当前属性，再原样回传 `description`、`email`、`expired`、`cannot_chg_passwd`、
   `passwd_never_expire`，只替换 `password`。读不到关键属性则中止该用户。

2. **密码不出现在命令行**：支持环境变量、交互式 `getpass`、标准输入三种方式。

3. **管理员保护**：当前登录账号自动跳过；管理员默认拒绝，必须 `--allow-admin`；
   无法读取用户组时也要求 `--allow-admin`。

4. **密码策略校验**：自动读取 DSM 的 `SYNO.Core.User.PasswordPolicy`，校验长度、
   大小写、数字、特殊字符、是否包含用户名。

5. **会话注销**：脚本退出前调用 DSM logout，异常退出也会在 `finally` 中注销。

---

## 测试

```bash
python -m unittest discover -s tests -v
```

测试使用本地假 DSM HTTP 服务，不连接真实 NAS。

---

## 常见问题

| 现象 | 处理 |
|------|------|
| `TLS 证书校验失败` | 加 `--insecure`（仅可信内网） |
| `账号或密码错误` | 检查账号密码；确认不是普通用户 |
| `需要双重验证` | 加 `--otp 123456` |
| `当前账号没有执行该操作的权限` | 账号必须属于 `administrators` 组 |
| `DSM 会话已超时` | 重新执行 |
| `HTTP 404` / 返回非 JSON | HTTPS 用 5001，HTTP 用 5000 |
| 只想查看不修改 | 使用 `list` 或 `reset --dry-run` |

---

## 限制

- 只管理 DSM **本地用户**（`type=local`），不管理 LDAP / 域用户。
- 需要 DSM 6.2+ / 7.x，且账号属于 `administrators` 组。
- 批量改密是串行执行；用户很多时请勿重复启动。
- 脚本不保存 NAS 密码；每次运行都需要重新提供。
