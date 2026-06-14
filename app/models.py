from datetime import datetime
from app.extensions import db


class AttackEvent(db.Model):
    __tablename__ = 'attack_events'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    attack_time = db.Column(db.DateTime, nullable=False, default=datetime.now)
    attack_type = db.Column(db.String(64), nullable=False)
    source_ip = db.Column(db.String(45), nullable=False)
    target_ip = db.Column(db.String(45), nullable=False)
    target_port = db.Column(db.Integer, nullable=True)
    severity = db.Column(db.String(16), nullable=False, default='中危')
    description = db.Column(db.Text, nullable=True)
    handler = db.Column(db.String(32), nullable=True)
    status = db.Column(db.String(16), nullable=False, default='未处理')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    SEVERITY_LIST = ['低危', '中危', '高危', '严重']
    STATUS_LIST = ['未处理', '处理中', '已处理', '误报']
    TYPE_LIST = ['DDoS', 'SQL注入', 'XSS', 'CSRF', '端口扫描', '暴力破解', '恶意软件', '钓鱼', 'WebShell', '其他']


class ConfigChange(db.Model):
    __tablename__ = 'config_changes'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    change_time = db.Column(db.DateTime, nullable=False, default=datetime.now)
    device_name = db.Column(db.String(128), nullable=False)
    device_ip = db.Column(db.String(45), nullable=False)
    config_type = db.Column(db.String(32), nullable=False)
    change_content = db.Column(db.Text, nullable=False)
    change_reason = db.Column(db.Text, nullable=True)
    operator = db.Column(db.String(32), nullable=False)
    is_rollback = db.Column(db.Boolean, nullable=False, default=False)
    change_status = db.Column(db.String(16), nullable=False, default='成功')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    CONFIG_TYPE_LIST = ['路由', '防火墙', '交换机', '服务器', '负载均衡', 'VPN', 'DNS', '其他']
    STATUS_LIST = ['成功', '失败', '已回滚']


class DesktopTicket(db.Model):
    __tablename__ = 'desktop_tickets'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ticket_number = db.Column(db.String(32), nullable=False, unique=True)
    create_time = db.Column(db.DateTime, nullable=False, default=datetime.now)
    requester = db.Column(db.String(32), nullable=False)
    department = db.Column(db.String(64), nullable=False)
    contact = db.Column(db.String(32), nullable=False)
    problem_type = db.Column(db.String(32), nullable=False)
    problem_description = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(16), nullable=False, default='中')
    assignee = db.Column(db.String(32), nullable=True)
    status = db.Column(db.String(16), nullable=False, default='待处理')
    solution = db.Column(db.Text, nullable=True)
    close_time = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    PROBLEM_TYPE_LIST = ['硬件故障', '软件安装', '网络连接', '系统故障', '账号权限', '数据恢复', '病毒查杀', '外设问题', '其他']
    PRIORITY_LIST = ['低', '中', '高', '紧急']
    STATUS_LIST = ['待处理', '处理中', '已解决', '已关闭', '已取消']


class DeviceAsset(db.Model):
    __tablename__ = 'device_assets'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    device_name = db.Column(db.String(128), nullable=False)
    device_type = db.Column(db.String(32), nullable=False, default='其他')
    brand = db.Column(db.String(64), nullable=True)
    model = db.Column(db.String(128), nullable=True)
    serial_number = db.Column(db.String(128), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    mac_address = db.Column(db.String(17), nullable=True)
    location = db.Column(db.String(256), nullable=True)
    rack_position = db.Column(db.String(64), nullable=True)
    responsible_person = db.Column(db.String(32), nullable=True)
    department = db.Column(db.String(64), nullable=True)
    purchase_date = db.Column(db.Date, nullable=True)
    warranty_expire = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(16), nullable=False, default='在线')
    firmware_version = db.Column(db.String(64), nullable=True)
    remarks = db.Column(db.Text, nullable=True)
    # SSH/Telnet 远程管理凭据
    mgmt_protocol = db.Column(db.String(8), nullable=False, default='ssh')
    mgmt_port = db.Column(db.Integer, nullable=False, default=22)
    mgmt_username = db.Column(db.String(64), nullable=True)
    mgmt_password = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    DEVICE_TYPE_LIST = [
        '路由器', '交换机', '防火墙', '服务器', '无线AP', '无线AC',
        '负载均衡', 'VPN网关', 'UPS电源', '存储设备', '光纤收发器', '其他'
    ]
    STATUS_LIST = ['在线', '离线', '维修中', '已报废', '备件']
    PROTOCOL_LIST = ['ssh', 'telnet']

    def __repr__(self):
        return f'<DeviceAsset {self.device_name}>'


class QuickLink(db.Model):
    __tablename__ = 'quick_links'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(128), nullable=False)
    url = db.Column(db.String(512), nullable=False)
    description = db.Column(db.String(256), nullable=True)
    username = db.Column(db.String(128), nullable=True)
    password = db.Column(db.String(256), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    @property
    def has_credentials(self):
        return bool(self.username or self.password)

    def __repr__(self):
        return f'<QuickLink {self.name}>'


class IPScanResult(db.Model):
    __tablename__ = 'ip_scan_results'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    scan_time = db.Column(db.DateTime, nullable=False, default=datetime.now)
    subnet = db.Column(db.String(64), nullable=False)
    total_ips = db.Column(db.Integer, nullable=False)
    alive_ips = db.Column(db.Integer, nullable=False, default=0)
    scan_duration = db.Column(db.Float, nullable=False, default=0.0)
    result_file = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    def __repr__(self):
        return f'<IPScan {self.subnet} {self.alive_ips}/{self.total_ips}>'