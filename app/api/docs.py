"""Swagger / OpenAPI 文档端点"""
from flask import Blueprint, jsonify

docs_bp = Blueprint('docs', __name__, url_prefix='/api')


@docs_bp.route('/openapi.json')
def openapi_spec():
    """OpenAPI 3.0 规范文档"""
    return jsonify({
        'openapi': '3.0.3',
        'info': {
            'title': '运维管理系统 API',
            'version': 'v1',
            'description': '企业级运维管理平台 RESTful API',
            'license': {'name': '内部使用', 'url': '#'}
        },
        'servers': [
            {'url': '/api/v1', 'description': '本地开发环境'}
        ],
        'tags': [
            {'name': '攻击事件', 'description': '网络安全攻击事件管理'},
            {'name': '配置变更', 'description': '网络配置变更记录管理'},
            {'name': '运维工单', 'description': '桌面运维工单管理'},
            {'name': '设备资产', 'description': '网络设备台账管理'},
            {'name': 'IP扫描', 'description': '内网IP存活扫描'},
            {'name': '安全资讯', 'description': 'CVE漏洞与安全资讯'},
            {'name': '报表', 'description': '周报/月报生成与导出'},
            {'name': '监控', 'description': '健康检查与性能指标'},
        ],
        'paths': {
            '/attacks': {
                'get': {
                    'tags': ['攻击事件'],
                    'summary': '获取攻击事件列表',
                    'parameters': [
                        {'name': 'page', 'in': 'query', 'schema': {'type': 'integer'}},
                        {'name': 'status', 'in': 'query', 'schema': {'type': 'string'}},
                        {'name': 'severity', 'in': 'query', 'schema': {'type': 'string'}},
                    ],
                    'responses': {'200': {'description': '成功'}}
                },
                'post': {
                    'tags': ['攻击事件'],
                    'summary': '创建攻击事件',
                    'responses': {'201': {'description': '已创建'}}
                }
            },
            '/attacks/{id}': {
                'get': {
                    'tags': ['攻击事件'],
                    'summary': '获取单个攻击事件',
                    'parameters': [{'name': 'id', 'in': 'path', 'required': True, 'schema': {'type': 'integer'}}],
                    'responses': {'200': {'description': '成功'}, '404': {'description': '不存在'}}
                },
                'put': {
                    'tags': ['攻击事件'],
                    'summary': '更新攻击事件',
                    'responses': {'200': {'description': '成功'}}
                },
                'delete': {
                    'tags': ['攻击事件'],
                    'summary': '删除攻击事件',
                    'responses': {'200': {'description': '成功'}}
                }
            },
            '/configs': {
                'get': {
                    'tags': ['配置变更'],
                    'summary': '获取配置变更列表',
                    'responses': {'200': {'description': '成功'}}
                },
                'post': {
                    'tags': ['配置变更'],
                    'summary': '创建配置变更',
                    'responses': {'201': {'description': '已创建'}}
                }
            },
            '/configs/{id}': {
                'get': {'tags': ['配置变更'], 'summary': '获取单个配置变更', 'responses': {'200': {'description': '成功'}}},
                'put': {'tags': ['配置变更'], 'summary': '更新配置变更', 'responses': {'200': {'description': '成功'}}},
                'delete': {'tags': ['配置变更'], 'summary': '删除配置变更', 'responses': {'200': {'description': '成功'}}}
            },
            '/tickets': {
                'get': {'tags': ['运维工单'], 'summary': '获取工单列表', 'responses': {'200': {'description': '成功'}}},
                'post': {'tags': ['运维工单'], 'summary': '创建工单', 'responses': {'201': {'description': '已创建'}}}
            },
            '/tickets/{id}': {
                'get': {'tags': ['运维工单'], 'summary': '获取单个工单', 'responses': {'200': {'description': '成功'}}},
                'put': {'tags': ['运维工单'], 'summary': '更新工单', 'responses': {'200': {'description': '成功'}}},
                'delete': {'tags': ['运维工单'], 'summary': '删除工单', 'responses': {'200': {'description': '成功'}}}
            },
            '/devices': {
                'get': {'tags': ['设备资产'], 'summary': '获取设备列表', 'responses': {'200': {'description': '成功'}}},
                'post': {'tags': ['设备资产'], 'summary': '创建设备', 'responses': {'201': {'description': '已创建'}}}
            },
            '/devices/{id}': {
                'get': {'tags': ['设备资产'], 'summary': '获取单个设备', 'responses': {'200': {'description': '成功'}}},
                'put': {'tags': ['设备资产'], 'summary': '更新设备', 'responses': {'200': {'description': '成功'}}},
                'delete': {'tags': ['设备资产'], 'summary': '删除设备', 'responses': {'200': {'description': '成功'}}}
            },
            '/ip-scan': {
                'post': {
                    'tags': ['IP扫描'],
                    'summary': '发起IP扫描',
                    'requestBody': {'content': {'application/json': {'schema': {'properties': {'subnet': {'type': 'string'}}}}}},
                    'responses': {'200': {'description': '扫描已发起'}}
                }
            },
            '/reports/data': {
                'get': {
                    'tags': ['报表'],
                    'summary': '获取报表数据',
                    'parameters': [
                        {'name': 'type', 'in': 'query', 'schema': {'type': 'string', 'enum': ['weekly', 'monthly']}},
                        {'name': 'start', 'in': 'query', 'schema': {'type': 'string'}},
                        {'name': 'end', 'in': 'query', 'schema': {'type': 'string'}},
                    ],
                    'responses': {'200': {'description': '成功'}}
                }
            },
            '/monitor/health': {
                'get': {'tags': ['监控'], 'summary': '健康检查', 'responses': {'200': {'description': '健康'}}}
            },
            '/monitor/metrics': {
                'get': {'tags': ['监控'], 'summary': '性能指标', 'responses': {'200': {'description': '成功'}}}
            },
            '/security/cves': {
                'get': {'tags': ['安全资讯'], 'summary': '获取最新CVE漏洞', 'responses': {'200': {'description': '成功'}}}
            },
            '/security/news': {
                'get': {'tags': ['安全资讯'], 'summary': '获取安全资讯', 'responses': {'200': {'description': '成功'}}}
            }
        }
    })


@docs_bp.route('/docs')
def api_docs_ui():
    """简易 API 文档浏览页"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>运维管理系统 - API 文档</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f7fa; color: #2c3e50; }
            .container { max-width: 960px; margin: 0 auto; padding: 40px 20px; }
            h1 { font-size: 28px; margin-bottom: 8px; }
            .subtitle { color: #6c757d; margin-bottom: 32px; }
            .endpoint { background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
            .method { display: inline-block; font-weight: 700; font-size: 13px; padding: 3px 10px; border-radius: 4px; margin-right: 12px; min-width: 64px; text-align: center; }
            .get { background: #d1fae5; color: #065f46; }
            .post { background: #dbeafe; color: #1e40af; }
            .put { background: #fef3c7; color: #92400e; }
            .delete { background: #fee2e2; color: #991b1b; }
            .path { font-family: monospace; font-size: 15px; font-weight: 600; }
            .desc { margin-top: 8px; color: #6c757d; font-size: 14px; }
            .spec-link { margin-bottom: 24px; }
            .spec-link a { color: #2563eb; text-decoration: none; font-size: 14px; }
            footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb; font-size: 13px; color: #9ca3af; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>运维管理系统 API</h1>
            <p class="subtitle">企业级运维管理平台 RESTful API &middot; v1</p>
            <p class="spec-link"><a href="/api/openapi.json">下载 OpenAPI 规范 (JSON)</a></p>

            <div class="endpoint"><span class="method get">GET</span><span class="path">/api/v1/attacks</span><p class="desc">获取攻击事件列表</p></div>
            <div class="endpoint"><span class="method post">POST</span><span class="path">/api/v1/attacks</span><p class="desc">创建攻击事件</p></div>
            <div class="endpoint"><span class="method get">GET</span><span class="path">/api/v1/attacks/{id}</span><p class="desc">获取单个攻击事件</p></div>
            <div class="endpoint"><span class="method put">PUT</span><span class="path">/api/v1/attacks/{id}</span><p class="desc">更新攻击事件</p></div>
            <div class="endpoint"><span class="method delete">DELETE</span><span class="path">/api/v1/attacks/{id}</span><p class="desc">删除攻击事件</p></div>
            <div class="endpoint"><span class="method get">GET</span><span class="path">/api/v1/configs</span><p class="desc">获取配置变更列表</p></div>
            <div class="endpoint"><span class="method post">POST</span><span class="path">/api/v1/configs</span><p class="desc">创建配置变更</p></div>
            <div class="endpoint"><span class="method get">GET</span><span class="path">/api/v1/configs/{id}</span><p class="desc">获取单个配置变更</p></div>
            <div class="endpoint"><span class="method put">PUT</span><span class="path">/api/v1/configs/{id}</span><p class="desc">更新配置变更</p></div>
            <div class="endpoint"><span class="method delete">DELETE</span><span class="path">/api/v1/configs/{id}</span><p class="desc">删除配置变更</p></div>
            <div class="endpoint"><span class="method get">GET</span><span class="path">/api/v1/tickets</span><p class="desc">获取运维工单列表</p></div>
            <div class="endpoint"><span class="method post">POST</span><span class="path">/api/v1/tickets</span><p class="desc">创建运维工单</p></div>
            <div class="endpoint"><span class="method get">GET</span><span class="path">/api/v1/tickets/{id}</span><p class="desc">获取单个工单</p></div>
            <div class="endpoint"><span class="method put">PUT</span><span class="path">/api/v1/tickets/{id}</span><p class="desc">更新工单</p></div>
            <div class="endpoint"><span class="method delete">DELETE</span><span class="path">/api/v1/tickets/{id}</span><p class="desc">删除工单</p></div>
            <div class="endpoint"><span class="method get">GET</span><span class="path">/api/v1/devices</span><p class="desc">获取设备资产列表</p></div>
            <div class="endpoint"><span class="method post">POST</span><span class="path">/api/v1/devices</span><p class="desc">创建设备资产</p></div>
            <div class="endpoint"><span class="method get">GET</span><span class="path">/api/v1/devices/{id}</span><p class="desc">获取单个设备</p></div>
            <div class="endpoint"><span class="method put">PUT</span><span class="path">/api/v1/devices/{id}</span><p class="desc">更新设备</p></div>
            <div class="endpoint"><span class="method delete">DELETE</span><span class="path">/api/v1/devices/{id}</span><p class="desc">删除设备</p></div>
            <div class="endpoint"><span class="method post">POST</span><span class="path">/api/v1/ip-scan</span><p class="desc">发起IP扫描</p></div>
            <div class="endpoint"><span class="method get">GET</span><span class="path">/api/v1/reports/data</span><p class="desc">获取报表数据</p></div>
            <div class="endpoint"><span class="method get">GET</span><span class="path">/monitor/health</span><p class="desc">健康检查</p></div>
            <div class="endpoint"><span class="method get">GET</span><span class="path">/monitor/metrics</span><p class="desc">性能指标</p></div>
            <div class="endpoint"><span class="method get">GET</span><span class="path">/monitor/info</span><p class="desc">应用信息</p></div>

            <footer>运维管理系统 V1.5 &mdash; API 文档自动生成</footer>
        </div>
    </body>
    </html>
    '''