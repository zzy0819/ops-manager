"""设备资产路由（使用服务层）"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from app.models import DeviceAsset
from app.services import DeviceService

devices_bp = Blueprint('devices', __name__, url_prefix='/devices')


@devices_bp.route('/')
def device_list():
    page = request.args.get('page', 1, type=int)
    devices = DeviceService.list_devices(
        page=page,
        device_type=request.args.get('device_type', ''),
        status=request.args.get('status', ''),
        keyword=request.args.get('keyword', '')
    )
    return render_template('devices.html', devices=devices,
                           device_type=request.args.get('device_type', ''),
                           status=request.args.get('status', ''),
                           keyword=request.args.get('keyword', ''),
                           device_type_list=DeviceAsset.DEVICE_TYPE_LIST,
                           status_list=DeviceAsset.STATUS_LIST)


@devices_bp.route('/new', methods=['GET', 'POST'])
def device_create():
    if request.method == 'POST':
        device = DeviceService.create(request.form)
        flash(f'设备 "{device.device_name}" 已添加', 'success')
        return redirect(url_for('devices.device_list'))
    return render_template('device_form.html', device=None,
                           device_type_list=DeviceAsset.DEVICE_TYPE_LIST,
                           status_list=DeviceAsset.STATUS_LIST)


@devices_bp.route('/<int:device_id>/edit', methods=['GET', 'POST'])
def device_edit(device_id):
    device = DeviceService.get_by_id(device_id)
    if not device:
        abort(404)
    if request.method == 'POST':
        DeviceService.update(device, request.form)
        flash(f'设备 "{device.device_name}" 已更新', 'success')
        return redirect(url_for('devices.device_list'))
    return render_template('device_form.html', device=device,
                           device_type_list=DeviceAsset.DEVICE_TYPE_LIST,
                           status_list=DeviceAsset.STATUS_LIST)


@devices_bp.route('/<int:device_id>/delete', methods=['POST'])
def device_delete(device_id):
    device = DeviceService.get_by_id(device_id)
    if not device:
        abort(404)
    name = device.device_name
    DeviceService.delete(device)
    flash(f'设备 "{name}" 已删除', 'success')
    return redirect(url_for('devices.device_list'))