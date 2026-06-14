"""报表路由（使用服务层）"""
from datetime import datetime, timedelta
from io import BytesIO
from flask import Blueprint, render_template, request, send_file
from app.models import AttackEvent, ConfigChange, DesktopTicket, DeviceAsset
from app.services import ReportService

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


@reports_bp.route('/', methods=['GET', 'POST'])
def reports():
    report_type = request.args.get('type', 'weekly')
    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')

    period_start, period_end, period_start_display, period_end_display, delta_days = \
        ReportService.get_report_period(report_type, start_str, end_str)

    attack_stats = ReportService.get_attack_stats(period_start, period_end)
    config_stats = ReportService.get_config_stats(period_start, period_end)
    ticket_stats = ReportService.get_ticket_stats(period_start, period_end)
    device_stats = ReportService.get_device_stats()

    report_data = {
        'report_type': report_type,
        'period_start': period_start_display,
        'period_end': period_end_display,
        'attack_total': attack_stats['total'],
        'attack_by_type': attack_stats['by_type'],
        'attack_by_severity': attack_stats['by_severity'],
        'attack_trend_labels': attack_stats['trend_labels'],
        'attack_trend_data': attack_stats['trend_data'],
        'config_total': config_stats['total'],
        'config_by_type': config_stats['by_type'],
        'config_by_status': config_stats['by_status'],
        'config_trend_labels': config_stats['trend_labels'],
        'config_trend_data': config_stats['trend_data'],
        'ticket_total': ticket_stats['total'],
        'ticket_pending': ticket_stats['pending'],
        'ticket_resolved': ticket_stats['resolved'],
        'device_total': device_stats['total'],
        'device_by_type': device_stats['by_type'],
        'delta_days': delta_days,
    }

    return render_template('reports.html', **report_data)


@reports_bp.route('/export/excel')
def export_excel():
    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')
    now = datetime.now()
    if start_str and end_str:
        period_start = datetime.strptime(start_str, '%Y-%m-%d')
        period_end = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
    else:
        period_start = now - timedelta(days=7)
        period_end = now

    excel_output = ReportService.generate_excel_report(period_start, period_end)
    filename = f'运维报告_{period_start.strftime("%Y%m%d")}_{(period_end - timedelta(days=1)).strftime("%Y%m%d")}.xlsx'
    return send_file(excel_output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=filename)


@reports_bp.route('/export/pdf')
def export_pdf():
    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')
    now = datetime.now()
    if start_str and end_str:
        period_start = datetime.strptime(start_str, '%Y-%m-%d')
        period_end = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
    else:
        period_start = now - timedelta(days=7)
        period_end = now

    period_start_display = period_start.strftime('%Y-%m-%d')
    period_end_display = (period_end - timedelta(days=1)).strftime('%Y-%m-%d')

    attack_stats = ReportService.get_attack_stats(period_start, period_end)
    config_stats = ReportService.get_config_stats(period_start, period_end)
    ticket_stats = ReportService.get_ticket_stats(period_start, period_end)
    device_stats = ReportService.get_device_stats()

    return render_template('report_print.html',
                           period_start=period_start_display,
                           period_end=period_end_display,
                           attack_total=attack_stats['total'],
                           attack_by_type=attack_stats['by_type'],
                           attack_by_severity=attack_stats['by_severity'],
                           attack_trend_labels=attack_stats['trend_labels'],
                           attack_trend_data=attack_stats['trend_data'],
                           config_total=config_stats['total'],
                           config_by_type=config_stats['by_type'],
                           config_trend_labels=config_stats['trend_labels'],
                           config_trend_data=config_stats['trend_data'],
                           ticket_total=ticket_stats['total'],
                           ticket_pending=ticket_stats['pending'],
                           ticket_resolved=ticket_stats['resolved'],
                           device_total=device_stats['total'],
                           device_by_type=device_stats['by_type'],
                           delta_days=(period_end - period_start).days)