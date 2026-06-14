from flask import Blueprint, render_template
from app.services import MainService

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    data = MainService.get_index_stats()
    return render_template('index.html',
                           attack_count=data['attack_count'],
                           config_count=data['config_count'],
                           ticket_count=data['ticket_count'],
                           pending_tickets=data['pending_tickets'],
                           scan_count=data['scan_count'],
                           device_count=data['device_count'],
                           recent_attacks=data['recent_attacks'],
                           recent_configs=data['recent_configs'],
                           recent_tickets=data['recent_tickets'])


@main_bp.route('/dashboard')
def dashboard():
    data = MainService.get_dashboard_data()
    return render_template('dashboard.html',
                           stats=data['stats'],
                           now=data['now'],
                           attack_severity_labels=data['attack_severity_labels'],
                           attack_severity_data=data['attack_severity_data'],
                           ticket_status_labels=data['ticket_status_labels'],
                           ticket_status_data=data['ticket_status_data'],
                           config_type_labels=data['config_type_labels'],
                           config_type_data=data['config_type_data'],
                           trend_labels=data['trend_labels'],
                           trend_attack_data=data['trend_attack_data'],
                           trend_config_data=data['trend_config_data'],
                           trend_ticket_data=data['trend_ticket_data'],
                           recent_attacks=data['recent_attacks'],
                           recent_configs=data['recent_configs'],
                           recent_tickets=data['recent_tickets'])