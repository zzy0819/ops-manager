"""配置备份服务层 —— 通过 SSH/Telnet 远程备份交换机配置"""
import threading
import time
from flask import current_app
from app.extensions import db
from app.models import DeviceAsset


class ConfigBackupService:
    """设备配置备份"""

    H3C_SAVE_COMMANDS = [
        'screen-length disable',
        'save force',
    ]

    @staticmethod
    def _ssh_execute(device: DeviceAsset, commands: list, timeout=30):
        """SSH 连接并执行命令，返回 (success, output)"""
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=device.ip_address,
                port=device.mgmt_port,
                username=device.mgmt_username,
                password=device.mgmt_password,
                timeout=10,
                look_for_keys=False,
                allow_agent=False,
            )
            output_lines = []
            for cmd in commands:
                stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
                out = stdout.read().decode('utf-8', errors='replace')
                err = stderr.read().decode('utf-8', errors='replace')
                output_lines.append(f'>>> {cmd}')
                if out.strip():
                    output_lines.append(out.strip())
                if err.strip():
                    output_lines.append(f'[STDERR] {err.strip()}')
                time.sleep(0.5)
            client.close()
            return True, '\n'.join(output_lines)
        except Exception as e:
            try:
                client.close()
            except Exception:
                pass
            return False, str(e)

    @staticmethod
    def _telnet_execute(device: DeviceAsset, commands: list, timeout=30):
        """Telnet 连接并执行命令，返回 (success, output)"""
        import telnetlib
        try:
            tn = telnetlib.Telnet(device.ip_address, device.mgmt_port, timeout=10)
            # 等待登录提示
            time.sleep(1)
            output_lines = []

            # 读缓冲区
            def read_until_prompt(prompt_list, timeout_val=5):
                try:
                    idx, _, data = tn.expect(
                        [p.encode('ascii') if isinstance(p, str) else p for p in prompt_list],
                        timeout=timeout_val
                    )
                    return data.decode('utf-8', errors='replace')
                except Exception:
                    return tn.read_very_eager().decode('utf-8', errors='replace')

            # 处理登录
            initial = read_until_prompt(['Username:', 'login:', 'Password:'], 5)
            output_lines.append(initial.strip())

            if 'Username:' in initial or 'login:' in initial:
                tn.write((device.mgmt_username + '\n').encode('ascii'))
                time.sleep(1)
                pw_prompt = read_until_prompt(['Password:'], 3)
                output_lines.append(pw_prompt.strip())

            if 'Password:' in initial or 'Password:' in pw_prompt if 'pw_prompt' in dir() else False:
                pass

            # 确保走到输入密码
            tn.write((device.mgmt_password + '\n').encode('ascii'))
            time.sleep(2)
            after_login = tn.read_very_eager().decode('utf-8', errors='replace')
            if after_login.strip():
                output_lines.append(after_login.strip())

            # 执行命令
            for cmd in commands:
                tn.write((cmd + '\n').encode('ascii'))
                time.sleep(2)
                resp = tn.read_very_eager().decode('utf-8', errors='replace')
                output_lines.append(f'>>> {cmd}')
                if resp.strip():
                    output_lines.append(resp.strip())

            tn.close()
            return True, '\n'.join(output_lines)
        except Exception as e:
            try:
                tn.close()
            except Exception:
                pass
            return False, str(e)

    @staticmethod
    def backup_device(device: DeviceAsset, override_protocol=None,
                      override_port=None, override_username=None,
                      override_password=None):
        """备份单台设备配置"""
        protocol = override_protocol or device.mgmt_protocol
        port = override_port or device.mgmt_port
        username = override_username or device.mgmt_username
        password = override_password or device.mgmt_password

        if not device.ip_address:
            return False, '设备未配置 IP 地址'
        if not username or not password:
            return False, '未配置 SSH/Telnet 凭据'

        # 临时覆盖端口
        original_port = device.mgmt_port
        if override_port:
            device.mgmt_port = override_port

        try:
            if protocol == 'ssh':
                ok, output = ConfigBackupService._ssh_execute(device, ConfigBackupService.H3C_SAVE_COMMANDS)
            else:
                ok, output = ConfigBackupService._telnet_execute(device, ConfigBackupService.H3C_SAVE_COMMANDS)
            return ok, output
        finally:
            if override_port:
                device.mgmt_port = original_port

    @staticmethod
    def backup_batch(device_ids: list, override_protocol=None, override_port=None,
                     override_username=None, override_password=None):
        """批量备份设备配置，返回每台设备的结果"""
        results = []
        for did in device_ids:
            device = db.session.get(DeviceAsset, did)
            if not device:
                results.append({'id': did, 'name': '?', 'ip': '?',
                                'success': False, 'output': '设备不存在'})
                continue

            ok, output = ConfigBackupService.backup_device(
                device,
                override_protocol=override_protocol,
                override_port=override_port,
                override_username=override_username,
                override_password=override_password,
            )
            results.append({
                'id': device.id,
                'name': device.device_name,
                'ip': device.ip_address,
                'protocol': override_protocol or device.mgmt_protocol,
                'success': ok,
                'output': output,
            })
        return results

    @staticmethod
    def get_switches(page=1, per_page=30, keyword=''):
        """获取交换机设备列表（用于备份页面）"""
        query = DeviceAsset.query.filter(DeviceAsset.device_type == '交换机')
        if keyword:
            query = query.filter(
                db.or_(
                    DeviceAsset.device_name.contains(keyword),
                    DeviceAsset.ip_address.contains(keyword),
                )
            )
        return query.order_by(DeviceAsset.ip_address).paginate(
            page=page, per_page=per_page, error_out=False)