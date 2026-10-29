import os
import json
import time
import re
from datetime import datetime, timedelta
import requests
import feedparser


def _load_cache(cache_file, max_age_seconds=3600):
    """读取 JSON 缓存，超时返回 None"""
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if time.time() - data.get('ts', 0) < max_age_seconds:
                return data.get('payload')
        except Exception:
            pass
    return None


def _save_cache(cache_file, payload):
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump({'ts': time.time(), 'payload': payload}, f, ensure_ascii=False)


SECURITY_RSS_FEEDS = [
    {'name': 'The Hacker News', 'url': 'https://feeds.feedburner.com/TheHackersNews', 'region': '国际'},
    {'name': 'BleepingComputer', 'url': 'https://www.bleepingcomputer.com/feed/', 'region': '国际'},
    {'name': '安全客 (AnQuanKe)', 'url': 'https://api.anquanke.com/data/v1/rss', 'region': '国内'},
    {'name': '嘶吼 (4hou)', 'url': 'https://www.4hou.com/feed', 'region': '国内'},
    {'name': 'Seebug Paper', 'url': 'https://paper.seebug.org/rss', 'region': '国内'},
    {'name': '腾讯玄武实验室', 'url': 'https://xlab.tencent.com/cn/atom.xml', 'region': '国内'},
    {'name': 'HackerNews', 'url': 'http://hackernews.cc/feed', 'region': '国内'},
    {'name': 'SecWiki News', 'url': 'https://www.sec-wiki.com/news/rss', 'region': '国内'},
]


def fetch_nvd_cves(cache_dir):
    """NVD CVE 数据获取（近 3 天漏洞，按严重度排序）"""
    cache_file = os.path.join(cache_dir, 'nvd_cves.json')
    cached = _load_cache(cache_file, max_age_seconds=3600)
    if cached:
        return cached

    end = datetime.utcnow()
    start = end - timedelta(days=3)
    cves = []

    try:
        params = {
            'pubStartDate': start.strftime('%Y-%m-%dT00:00:00.000'),
            'pubEndDate': end.strftime('%Y-%m-%dT23:59:59.999'),
            'resultsPerPage': 50
        }
        resp = requests.get('https://services.nvd.nist.gov/rest/json/cves/2.0',
                            params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get('vulnerabilities', []):
                cve = item.get('cve', {})
                cve_id = cve.get('id', '')
                desc = ''
                for d in cve.get('descriptions', []):
                    if d.get('lang') == 'en':
                        desc = d.get('value', '')[:200]
                        break
                metrics = cve.get('metrics', {}).get('cvssMetricV31', [])
                cvss_score = None
                severity = 'N/A'
                if metrics:
                    cvss_data = metrics[0].get('cvssData', {})
                    cvss_score = cvss_data.get('baseScore')
                    sev_map = {'CRITICAL': 'CRITICAL', 'HIGH': 'HIGH', 'MEDIUM': 'MEDIUM', 'LOW': 'LOW'}
                    severity = sev_map.get(cvss_data.get('baseSeverity', ''), 'N/A')
                pub_date = cve.get('published', '')[:10]
                cves.append({
                    'id': cve_id,
                    'description': desc,
                    'severity': severity,
                    'cvss_score': cvss_score,
                    'pub_date': pub_date
                })
    except Exception as e:
        cves.append({'id': 'ERROR', 'description': f'NVD API 请求失败: {str(e)[:100]}',
                     'severity': 'INFO', 'cvss_score': None, 'pub_date': ''})

    # 过滤 Critical + High，按严重度排序
    filtered = [c for c in cves if c['severity'] in ('CRITICAL', 'HIGH')]
    filtered.sort(key=lambda x: (0 if x['severity'] == 'CRITICAL' else 1, -(x['cvss_score'] or 0)))

    result = filtered[:40]
    _save_cache(cache_file, result)
    return result


def fetch_security_news(cache_dir):
    """安全新闻 RSS 抓取（国内外）"""
    cache_file = os.path.join(cache_dir, 'security_news.json')
    cached = _load_cache(cache_file, max_age_seconds=3600)
    if cached:
        return cached

    all_news = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    for feed_info in SECURITY_RSS_FEEDS:
        try:
            resp = requests.get(feed_info['url'], headers=headers, timeout=10)
            if resp.status_code == 200:
                feed = feedparser.parse(resp.text)
                for entry in feed.entries[:8]:
                    title = entry.get('title', '')
                    link = entry.get('link', '')
                    summary = entry.get('summary', '')
                    summary = re.sub(r'<[^>]+>', '', summary)[:200]
                    pub_date = entry.get('published', '')[:25]
                    all_news.append({
                        'title': title,
                        'link': link,
                        'summary': summary,
                        'source': feed_info['name'],
                        'region': feed_info['region'],
                        'pub_date': pub_date
                    })
        except Exception:
            continue

    all_news.sort(key=lambda x: x['source'])
    _save_cache(cache_file, all_news)
    return all_news