import os
from datetime import datetime
from flask import Blueprint, render_template, current_app
from app.services.security_service import fetch_nvd_cves, fetch_security_news

security_bp = Blueprint('security', __name__, url_prefix='/security-center')


@security_bp.route('/')
def security_center():
    cache_dir = os.path.join(current_app.root_path, '..', 'cache')
    cves = fetch_nvd_cves(cache_dir)
    news = fetch_security_news(cache_dir)
    return render_template('security_center.html', cves=cves, news=news,
                           now=datetime.now().strftime('%Y-%m-%d %H:%M'))