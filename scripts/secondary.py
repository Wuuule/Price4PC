"""Public deal references. Detail timestamps prevent old deals becoming live prices."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup


def published_at(soup):
    node = soup.select_one('meta[name="weibo:webpage:update_at"]')
    if node:
        try:
            return datetime.strptime(node.get('content', ''), '%Y-%m-%d %H:%M:%S %z').astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        except ValueError:
            pass
    for node in soup.select('meta[property="article:published_time"], time[datetime]'):
        raw = node.get('content') or node.get('datetime')
        try:
            value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            if value.tzinfo:
                return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        except (ValueError, AttributeError):
            pass
    return None


def recent_report(row, now):
    if row.get('report_state') == 'expired' or not row.get('reported_at'):
        return False
    published = datetime.fromisoformat(row['reported_at'].replace('Z', '+00:00'))
    checked = datetime.fromisoformat(now.replace('Z', '+00:00'))
    return timedelta(0) <= checked - published <= timedelta(hours=72)


def parse_detail(html, url, products, now, make_offer):
    soup = BeautifulSoup(html, 'html.parser')
    box = soup.select_one('.info-right')
    title = box.select_one('h1') if box else None
    price = box.select_one('.price-large') if box else None
    if not title or not price:
        return []
    from collect import parse_price
    raw_title = title.get_text(' ', strip=True)
    amount = parse_price(price.get_text('', strip=True))
    rows = []
    for product in products:
        row = make_offer(product, 'smzdm', raw_title, amount, url, url, now)
        if not row:
            continue
        time = box.select_one('.time')
        row['reported_date_text'] = time.get_text(' ', strip=True) if time else '报料时间未确认'
        row['reported_at'] = published_at(soup)
        row['report_state'] = 'expired' if re.search(r'售罄|已结束|已过期|已失效', box.select_one('.title-box').get_text(' ', strip=True) if box.select_one('.title-box') else '') else 'unverified'
        channel = box.select_one('.mall, .mall-name, .mall-title')
        # Inspect the article's own purchase panel, never related product widgets.
        channel_text = channel.get_text(' ', strip=True) if channel else box.get_text(' ', strip=True)
        row['merchant_platform'] = next((p for p, name in [('jd', '京东'), ('taobao', '天猫'), ('taobao', '淘宝'), ('pdd', '拼多多')] if name in channel_text), None)
        desc = box.select_one('.price-desc')
        terms = desc.get_text(' ', strip=True) if desc else ''
        row['conditions'] = '什么值得买报料，尚未核实当前成交价' + ('；' + terms if terms else '')
        row['reference_only'] = not recent_report(row, now)
        if row['reference_only']:
            row['conditions'] += '；旧报料、已失效或时间未确认，不计入当前最低价'
        rows.append(row)
    return rows


def discover(html, url, products, matcher):
    soup = BeautifulSoup(html, 'html.parser')
    links = set()
    for node in soup.select('.haojia-card-container .card-right-box-title, .feed-row-wide .feed-block-title a, .feed-row .feed-block-title a'):
        title = node.get_text(' ', strip=True)
        href = urljoin(url, node.get('href', ''))
        if re.fullmatch(r'https://www\.smzdm\.com/p/\d+/?', href) and any(matcher(title, p) for p in products):
            links.add(href)
    return links


def collect_sources(config, products, now, make_offer, matcher, headers):
    references, statuses = [], []
    def get(url):
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            html = response.text
            # Includes script-only Tencent/Aliyun captcha pages.
            if response.status_code == 202 or re.search(r'TencentCaptcha|AliyunCaptcha|WafCaptcha|人机验证', html):
                return None, 'blocked', '公开页面返回人机验证，停止读取'
            return html, 'ok', '公开页面可读取'
        except requests.RequestException as e:
            return None, 'error', type(e).__name__ + '：无法读取公开页面'
    urls = config.get('smzdm_category_urls', [])
    detail_urls = set(config.get('smzdm_detail_urls', []))
    with ThreadPoolExecutor(max_workers=2) as pool:
        for url, (html, state, message) in zip(urls, pool.map(get, urls)):
            links = discover(html, url, products, matcher) if html else set()
            detail_urls.update(links)
            statuses.append({'platform':'smzdm', 'status':state if not html else 'ok' if links else 'no_matches', 'message':message + f'；发现 {len(links)} 条匹配报料链接', 'url':url, 'checked_at':now, 'count':0})
        details = sorted(detail_urls)[:30]
        for url, (html, state, message) in zip(details, pool.map(get, details)):
            rows = parse_detail(html, url, products, now, make_offer) if html else []
            references.extend(rows)
            statuses.append({'platform':'smzdm', 'product_id':rows[0]['product_id'] if rows else None, 'status':'ok' if rows else state if not html else 'no_matches', 'message':f'读取 {len(rows)} 条报料；近期 {sum(not r["reference_only"] for r in rows)} 条，旧报料单独保留' if rows else message + '；未提取匹配规格的报价', 'url':url, 'checked_at':now, 'count':len(rows)})
        probes = config.get('manmanbuy_probe_urls', [])
        for url, (html, state, message) in zip(probes, pool.map(get, probes)):
            statuses.append({'platform':'manmanbuy','status':state if not html else 'no_matches','message':message + '；尚未打通自动价格读取', 'url':url,'checked_at':now,'count':0})
    if config.get('miaomiaozhe_query_url'):
        html, state, message = get(config['miaomiaozhe_query_url'])
        statuses.append({'platform':'miaomiaozhe','status':'needs_link' if html else state,'message':'历史价查询需要具体商品链接，可能要求授权；尚未接入自动价格数据' if html else message, 'url':config['miaomiaozhe_query_url'],'checked_at':now,'count':0})
    return list({r['id']:r for r in references}.values()), statuses
