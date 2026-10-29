# ops-manager

运维工具集（monorepo）。本仓库按“子项目”组织，每个子目录都是一个可以独立运行的子项目，并带有自己的 `README.md`。

## 子项目一览

| 子项目 | 说明 | 技术栈 | 入口 |
|--------|------|--------|------|
| [web-app](./web-app) | 企业运维管理 Web 系统：攻击事件、配置变更、工单、设备台账、IP 扫描、网络诊断、群晖用户管理等 | Flask + SQLAlchemy + Bootstrap 5 | `python run.py` |
| [synology-user-manager](./synology-user-manager) | 群晖 NAS 用户扫描 / 批量改密单文件脚本 | 仅 Python 标准库 | `python synology_user_manager.py` |
| [auto-ssh-backup](./auto-ssh-backup) | 批量 SSH 登录华三交换机并保存配置 | netmiko + openpyxl | `python auto-ssh-back.py -f devices.xlsx` |
| [h3c-ops-agent](./h3c-ops-agent) | 华三交换机批量运维 Agent：巡检 + 标准团体名 + 自动接入 Zabbix + 配置备份 | paramiko + requests + openpyxl | `python run.py full --apply` |

## 环境要求

- Python 3.10+
- 各子项目的依赖相互独立，按各自 `README.md` / `requirements.txt` 安装

根目录的 `.venv` 是开发环境共享虚拟环境；`.idea` 是 IDE 配置；`.workbuddy` 是内部研发笔记，均不属于子项目。

## 快速开始

```bash
# 1. 进入某个子项目
cd web-app

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行
python run.py
```

每个子项目的详细说明、配置项、测试命令见各自目录下的 `README.md`。

## 目录结构

```
ops-manager/
├── web-app/                 # 子项目：运维管理 Web 系统
├── synology-user-manager/   # 子项目：群晖用户扫描/批量改密脚本
├── auto-ssh-backup/         # 子项目：华三交换机配置批量保存
├── h3c-ops-agent/           # 子项目：华三交换机巡检/团体名/Zabbix 接入/备份
├── .gitignore
├── README.md                # 本文件（monorepo 索引）
└── .venv/                   # 开发环境虚拟环境（不入库）
```
