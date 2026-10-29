#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""华三交换机批量运维 Agent。

模块划分：
    config      配置加载（JSON + 默认值 + 环境变量覆盖）
    inventory   设备清单（xlsx / csv / json）
    ssh         Comware 交互式会话（paramiko）
    inspect     巡检采集与健康判定
    snmp        标准团体名配置
    zabbix      Zabbix API 接入
    backup      配置备份与差异对比
    report      控制台 / Markdown / Excel 报告
    runner      并发调度
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
