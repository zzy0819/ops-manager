"""设备资产服务层"""
from datetime import datetime
from app.extensions import db
from app.models import DeviceAsset


class DeviceService:
    """设备资产业务逻辑"""

    @staticmethod
    def list_devices(page=1, per_page=15, device_type='', status='', keyword=''):
        query = DeviceAsset.query
        if device_type:
            query = query.filter(DeviceAsset.device_type == device_type)
        if status:
            query = query.filter(DeviceAsset.status == status)
        if keyword:
            query = query.filter(
                db.or_(
                    DeviceAsset.device_name.contains(keyword),
                    DeviceAsset.ip_address.contains(keyword),
                    DeviceAsset.serial_number.contains(keyword),
                    DeviceAsset.responsible_person.contains(keyword)
                )
            )
        return query.order_by(DeviceAsset.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False)

    @staticmethod
    def get_by_id(device_id):
        return db.session.get(DeviceAsset, device_id)

    @staticmethod
    def create(data: dict):
        device = DeviceAsset(
            device_name=data['device_name'],
            device_type=data.get('device_type', '其他'),
            brand=data.get('brand', ''),
            model=data.get('model', ''),
            serial_number=data.get('serial_number', ''),
            ip_address=data.get('ip_address', ''),
            mac_address=data.get('mac_address', ''),
            location=data.get('location', ''),
            rack_position=data.get('rack_position', ''),
            responsible_person=data.get('responsible_person', ''),
            department=data.get('department', ''),
            purchase_date=datetime.strptime(data['purchase_date'], '%Y-%m-%d').date() if data.get('purchase_date') else None,
            warranty_expire=datetime.strptime(data['warranty_expire'], '%Y-%m-%d').date() if data.get('warranty_expire') else None,
            status=data.get('status', '在线'),
            firmware_version=data.get('firmware_version', ''),
            remarks=data.get('remarks', ''),
            mgmt_protocol=data.get('mgmt_protocol', 'ssh'),
            mgmt_port=int(data.get('mgmt_port', 22)),
            mgmt_username=data.get('mgmt_username', ''),
            mgmt_password=data.get('mgmt_password', '')
        )
        db.session.add(device)
        db.session.commit()
        return device

    @staticmethod
    def update(device, data: dict):
        device.device_name = data['device_name']
        device.device_type = data.get('device_type', '其他')
        device.brand = data.get('brand', '')
        device.model = data.get('model', '')
        device.serial_number = data.get('serial_number', '')
        device.ip_address = data.get('ip_address', '')
        device.mac_address = data.get('mac_address', '')
        device.location = data.get('location', '')
        device.rack_position = data.get('rack_position', '')
        device.responsible_person = data.get('responsible_person', '')
        device.department = data.get('department', '')
        device.purchase_date = datetime.strptime(data['purchase_date'], '%Y-%m-%d').date() if data.get('purchase_date') else None
        device.warranty_expire = datetime.strptime(data['warranty_expire'], '%Y-%m-%d').date() if data.get('warranty_expire') else None
        device.status = data.get('status', '在线')
        device.firmware_version = data.get('firmware_version', '')
        device.remarks = data.get('remarks', '')
        device.mgmt_protocol = data.get('mgmt_protocol', 'ssh')
        device.mgmt_port = int(data.get('mgmt_port', 22))
        device.mgmt_username = data.get('mgmt_username', '')
        if data.get('mgmt_password'):
            device.mgmt_password = data['mgmt_password']
        db.session.commit()
        return device

    @staticmethod
    def delete(device):
        db.session.delete(device)
        db.session.commit()
