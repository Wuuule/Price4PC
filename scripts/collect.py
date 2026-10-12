#!/usr/bin/env python3
"""Public search discovery + explicitly identified offers. No login bypass.

Search observations are separated from third-party deal reports. A scraped
listing is not proof of checkout eligibility or exhaustive market coverage.
"""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from pricing import active, calculate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'web/data'
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36', 'Accept-Language': 'zh-CN,zh;q=0.9'}
PLATFORMS = {
    'jd': {'name': '京东', 'search': 'https://search.jd.com/Search?keyword={query}&enc=utf-8', 'host': ('jd.com',), 'cards': '.gl-item', 'title': '.p-name', 'price': '.p-price i', 'link': '.p-name a'},
    'taobao': {'name': '淘宝', 'search': 'https://s.taobao.com/search?q={query}', 'host': ('taobao.com', 'tmall.com'), 'cards': '[class*="Card--doubleCard"], .item.J_MouserOnverReq', 'title': '[class*="title--"], .title', 'price': '[class*="priceInt--"], .price strong', 'link': 'a[href]'},
    'pdd': {'name': '拼多多', 'search': 'https://mobile.yangkeduo.com/search_result.html?search_key={query}', 'host': ('yangkeduo.com', 'pinduoduo.com'), 'cards': '[data-goods-id]', 'title': '[class*="goodsName"], [class*="goods-name"]', 'price': '[class*="price"]', 'link': 'a[href]'},
    'smzdm': {'name': '好价报料', 'search': 'https://search.smzdm.com/?c=faxian&s={query}&order=time&v=b', 'host': ('smzdm.com',), 'cards': '.feed-row-wide, .feed-row', 'title': '.feed-block-title', 'price': '.z-highlight, .feed-price', 'link': '.feed-block-title a'}
}


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def load(path, fallback):
    return json.loads(path.read_text()) if path.exists() else fallback


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def allowed_url(url, hosts):
    parsed = urlparse(url)
    host = parsed.hostname or ''
    return parsed.scheme in ('http', 'https') and not parsed.username and any(host == h or host.endswith('.' + h) for h in hosts)


def matches(title, product):
    title = title.lower().replace('®', '').replace('™', '')
    title = re.sub(r'\b(rtx|rx)\s*(?=\d)', r'\1 ', title)
    if product['id'] == 'ultra7-270k' and re.search(r'270k\s*plus', title):
        return False
    if not re.search(product['match'], title, re.I):
        return False
    # Whole computers, accessories, bundles and used units are not comparable.
    if re.search(r'整机|组装机|游戏主机|电脑主机|板u|主板套|套装|二手|拆机|维修|租赁|定金|订金|散热器|水冷|保护盖|外壳|硬盘盒|扩展卡', title):
        return False
    if product['category'] == 'RAM':
        if not re.search(r'(?<!\d)16\s*(?:gb|g)(?![a-z0-9])', title):
            return False
        if re.search(r'16\s*[gG](?:[bB])?\s*[xX×*]\s*2|32\s*g|笔记本|sodimm|ecc|服务器', title):
            return False
        if not re.search(r'单条|单根|1\s*[x×*]\s*16|16\s*g(?:b)?\s*[x×*]\s*1', title):
            return False
    if product['category'] == 'SSD':
        if not re.search(r'(?<!\d)1\s*t(?:b)?(?![a-z0-9])|1000\s*g(?:b)?|1024\s*g(?:b)?', title):
            return False
        if not re.search(r'nvme', title) or not re.search(r'm\.?2', title):
            return False
    # Multiple models in one title often mean a cheap default variant.
    tokens = re.findall(r'(?<![a-z0-9])(?:\d{4}(?:\s*x3d|\s*xt|\s*ti|\s*x)?|\d{3}\s*k)(?![a-z0-9])', title)
    # Clock rates/capacities are excluded from model checks.
    tokens = [t for t in tokens if re.fullmatch(r'\d{4}', t) is None or t.startswith(('50', '90', '78', '97', '98'))]
    if len(set(t.replace(' ', '') for t in tokens)) > 1:
        return False
    return True


def parse_price(text):
    text = text.replace(',', '').strip()
    # No ranges, installments, foreign currency, deposits, or percent discounts.
    if re.search(r'起|每期|分期|定金|订金|\d\s*[-~～]\s*\d|美元|港币|HK\$|\$|%', text):
        return None
    number = re.fullmatch(r'(?:[¥￥]|人民币)?\s*(\d+(?:\.\d{1,2})?)\s*(?:元|元起)?(?:（[^）]*）|\([^)]*\))?', text)
    return float(number[1]) if number else None


def offer(product, platform, title, price, url, source_url, now, **extra):
    if not matches(title, product) or price is None or not product['min'] <= price <= product['max']:
        return None
    hosts = PLATFORMS[platform]['host']
    if not allowed_url(url, hosts):
        return None
    if platform == 'jd' and not re.search(r'/\d+\.html', urlparse(url).path):
        return None
    if platform == 'taobao' and not re.search(r'(?:id=\d+|/item/)', url):
        return None
    if platform == 'pdd' and not re.search(r'goods_id=\d+', url):
        return None
    canonical = url.split('#')[0]
    identity = hashlib.sha256((product['id'] + platform + canonical).encode()).hexdigest()[:20]
    return {'id': identity, 'product_id': product['id'], 'platform': platform, 'title': title[:300],
            'base_price': price, 'final_price': price, 'shipping': None,
            'price_kind': 'reported' if platform == 'smzdm' else 'listed',
            'conditions': '第三方报料，需核对时效、SKU、运费及领券资格' if platform == 'smzdm' else '页面展示价；SKU、运费及结算优惠需在平台确认',
            'url': canonical, 'source_url': source_url, 'observed_at': now,
            'applied_discounts': [], 'excluded_discounts': [], **extra}


def parse_page(html, platform, product, source_url, now):
    soup = BeautifulSoup(html, 'html.parser')
    cfg = PLATFORMS[platform]
    results = []
    for card in soup.select(cfg['cards'])[:80]:
        title_node, price_node, link = card.select_one(cfg['title']), card.select_one(cfg['price']), card.select_one(cfg['link'])
        if not all((title_node, price_node, link)):
            continue
        title = title_node.get_text(' ', strip=True)
        # SMZDM puts its price tag inside the title; remove only that tag's text.
        if platform == 'smzdm':
            title = title.replace(price_node.get_text(' ', strip=True), '').strip()
        price_text = price_node.get_text('', strip=True)
        if platform == 'taobao':
            fraction = card.select_one('[class*="priceFloat--"]')
            if fraction and '.' not in price_text:
                price_text += fraction.get_text('', strip=True)
        price = parse_price(price_text)
        url = urljoin(source_url, link.get('href', ''))
        data = offer(product, platform, title, price, url, source_url, now)
        if data:
            if platform == 'smzdm':
                mall = card.select_one('.feed-block-extras, .feed-block-footer')
                text = mall.get_text(' ', strip=True) if mall else ''
                data['merchant_platform'] = next((p for p, name in [('jd', '京东'), ('taobao', '天猫'), ('taobao', '淘宝'), ('pdd', '拼多多')] if name in text), None)
                date = card.select_one('time, .feed-block-extras .time, .feed-block-extras span')
                data['reported_date_text'] = date.get_text(' ', strip=True)[:100] if date else None
            results.append(data)
    # Schema.org Product offers are also supported on concrete product pages.
    if platform != 'smzdm':
        for node in soup.select('script[type="application/ld+json"]'):
            try:
                payload = json.loads(node.string or node.get_text())
            except (ValueError, TypeError):
                continue
            queue = payload if isinstance(payload, list) else [payload]
            while queue:
                item = queue.pop()
                if not isinstance(item, dict):
                    continue
                queue.extend(item.get('@graph', []))
                if item.get('@type') != 'Product':
                    continue
                offers = item.get('offers', [])
                offers = offers if isinstance(offers, list) else [offers]
                for entry in offers:
                    if not isinstance(entry, dict) or entry.get('@type') == 'AggregateOffer':
                        continue
                    if entry.get('priceCurrency') != 'CNY' or not entry.get('availability', '').endswith('InStock'):
                        continue
                    data = offer(product, platform, item.get('name', ''), parse_price(str(entry.get('price', ''))), urljoin(source_url, entry.get('url', source_url)), source_url, now)
                    if data:
                        results.append(data)
    return list({r['id']: r for r in results}.values())


def page_status(html, offers):
    if offers:
        return 'ok', f'采集 {len(offers)} 条匹配商品'
    if re.search(r'TencentCaptcha|AliyunCaptcha|WafCaptcha', html):
        return 'blocked', '公开页面返回人机验证'
    text = BeautifulSoup(html, 'html.parser').get_text(' ', strip=True)
    if re.search(r'验证码|验证后|安全验证|京东验证|滑块验证|访问过于频繁|访问受限|人机验证|captcha|risk control', text, re.I):
        return 'blocked', '平台安全验证或访问限制'
    if re.search(r'请登录|登录后|扫码登录|登录淘宝|登录拼多多', text):
        return 'login_required', '需要平台登录才能读取价格'
    return 'no_matches', '未提取到符合规格的价格；可能为空、动态加载或页面结构变更'


def http_job(job):
    platform, product, url, now = job
    try:
        response = requests.get(url, headers=HEADERS, timeout=18)
        response.raise_for_status()
        if response.status_code == 202:
            return [], 'blocked', '平台返回安全挑战页面（HTTP 202）'
        if not allowed_url(response.url, PLATFORMS[platform]['host']):
            return [], 'blocked', '页面跳转到登录或非商品域名'
        response.encoding = response.apparent_encoding
        rows = parse_page(response.text, platform, product, response.url, now)
        status, message = page_status(response.text, rows)
        return rows, status, message
    except requests.RequestException as error:
        return [], 'error', type(error).__name__ + '：网络或 HTTP 错误'


async def render_jobs(jobs, prior):
    from playwright.async_api import async_playwright
    semaphore = asyncio.Semaphore(3)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(locale='zh-CN', user_agent=HEADERS['User-Agent'])
        async def render(index, job):
            platform, product, url, now = job
            if prior[index][0] or platform == 'smzdm':
                return prior[index]
            async with semaphore:
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=18000)
                    try:
                        await page.wait_for_selector(PLATFORMS[platform]['cards'], timeout=6000)
                    except Exception:
                        pass
                    html = await page.content()
                    if not allowed_url(page.url, PLATFORMS[platform]['host']):
                        return [], 'blocked', '浏览器跳转到登录或非商品域名'
                    rows = parse_page(html, platform, product, page.url, now)
                    status, message = page_status(html, rows)
                    return rows, status, message
                except Exception as error:
                    return [], 'error', type(error).__name__ + '：浏览器采集失败'
                finally:
                    await page.close()
        try:
            return await asyncio.gather(*(render(i, job) for i, job in enumerate(jobs)))
        finally:
            await browser.close()


def validate_feed(row, products, now):
    product = next((p for p in products if p['id'] == row.get('product_id')), None)
    platform = row.get('platform')
    if not product or platform not in ('jd', 'taobao', 'pdd'):
        raise ValueError('Unknown product/platform')
    if row.get('currency') != 'CNY' or not row.get('in_stock') or not row.get('sku_confirmed'):
        raise ValueError('Feed requires CNY, in_stock and sku_confirmed')
    observed = datetime.fromisoformat(row['observed_at'].replace('Z', '+00:00'))
    current = datetime.fromisoformat(now.replace('Z', '+00:00'))
    if observed.tzinfo is None or not timedelta(0) <= current-observed <= timedelta(hours=24):
        raise ValueError('Feed observations must be within 24 hours')
    source = row['evidence_url']
    if not allowed_url(source, PLATFORMS[platform]['host']):
        raise ValueError('Evidence must be from merchant platform')
    data = offer(product, platform, row['title'], parse_price(str(row['base_price'])), row['url'], source, row['observed_at'])
    if not data:
        raise ValueError('Unmatched product, invalid price or URL')
    if row.get('shipping') is None:
        raise ValueError('Shipping must be explicit')
    for coupon in row.get('coupons', []):
        if not allowed_url(coupon.get('evidence_url', ''), PLATFORMS[platform]['host']):
            raise ValueError('Coupon evidence must be from platform')
    data.update(calculate(row['base_price'], row.get('coupons', []), row['shipping']))
    data.update(price_kind='calculated', shipping=row['shipping'], conditions=row.get('conditions', '已按来源明确的公开优惠及运费计算'))
    expires = [c['ends_at'] for c in row.get('coupons', []) if c.get('ends_at') and c.get('label', '优惠') in [d['label'] for d in data['applied_discounts']]]
    data['coupon_expires_at'] = min(expires, key=lambda t: datetime.fromisoformat(t.replace('Z', '+00:00')), default=None)
    # Distinct coupon plans must not overwrite one another on the same SKU.
    plan = json.dumps(row.get('coupons', []), sort_keys=True, ensure_ascii=False)
    data['id'] = hashlib.sha256((data['id'] + plan + str(row['shipping'])).encode()).hexdigest()[:20]
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', action='store_true')
    parser.add_argument('--no-network', action='store_true')
    args = parser.parse_args()
    now = utcnow()
    products = load(ROOT/'config/products.json', [])
    jobs = [(platform, product, cfg['search'].format(query=quote(product['query'])), now) for platform, cfg in PLATFORMS.items() for product in products]
    # Search additional Double-11 leads during the season; no assumed dates or rules.
    if datetime.now(timezone.utc).month in (10, 11):
        jobs.extend(('smzdm', p, PLATFORMS['smzdm']['search'].format(query=quote(p['query']+' 双11')), now) for p in products)
    for listing in load(ROOT/'config/listings.json', []):
        product = next(p for p in products if p['id'] == listing['product_id'])
        if listing['platform'] not in ('jd', 'taobao', 'pdd') or not allowed_url(listing['url'], PLATFORMS[listing['platform']]['host']):
            raise ValueError('Listing URL must be a supported platform URL')
        jobs.append((listing['platform'], product, listing['url'], now))
    if args.no_network:
        results = [([], 'not_run', '首次网络采集尚未运行') for _ in jobs]
    else:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(http_job, jobs))
        if args.browser:
            try:
                results = asyncio.run(render_jobs(jobs, results))
            except Exception as error:
                print('Browser unavailable:', type(error).__name__, file=sys.stderr)
    rows, statuses = [], []
    for job, (found, status, message) in zip(jobs, results):
        platform, product, url, _ = job
        rows.extend(found)
        statuses.append({'platform': platform, 'product_id': product['id'], 'status': status, 'message': message, 'url': url, 'checked_at': now, 'count': len(found)})
    # Public secondary sources supply dated, explicitly unverified deal references.
    references = []
    if not args.no_network:
        from secondary import collect_sources, recent_report
        references, secondary_statuses = collect_sources(load(ROOT/'config/secondary-sources.json', {}), products, now, offer, matches, HEADERS)
        statuses.extend(secondary_statuses)
        rows.extend(r for r in references if not r['reference_only'])
    # Undated search-list reports must not silently become current prices.
    rows = [r for r in rows if r['price_kind'] != 'reported' or r.get('reported_at')]
    # Optional authorized data provider; a secret URL is never published in output.
    feed_url = os.environ.get('PRICE_FEED_URL')
    if feed_url and not args.no_network:
        try:
            if urlparse(feed_url).scheme != 'https':
                raise ValueError('Feed requires HTTPS')
            response = requests.get(feed_url, timeout=25)
            response.raise_for_status()
            feed = response.json()
            accepted, rejected = 0, 0
            for raw in feed.get('offers', []):
                try:
                    rows.append(validate_feed(raw, products, now))
                    accepted += 1
                except (ValueError, KeyError, TypeError):
                    rejected += 1
            statuses.append({'platform': 'feed', 'status': 'ok' if accepted else 'no_matches', 'message': f'有效 {accepted} 条，校验拒绝 {rejected} 条', 'checked_at': now, 'count': accepted})
        except Exception as error:
            statuses.append({'platform': 'feed', 'status': 'error', 'message': type(error).__name__+'：价格数据源读取失败', 'checked_at': now, 'count': 0})
    offers = list({row['id']: row for row in rows}.values())
    # Current offers contain ONLY this run's results. Prior offers remain in history.
    history = load(DATA/'history.json', [])
    seen = {(r['id'], r.get('reported_at') or r['observed_at'], r['final_price'], r['price_kind']) for r in history}
    for row in list({r['id']: r for r in offers + references}.values()):
        key = (row['id'], row.get('reported_at') or row['observed_at'], row['final_price'], row['price_kind'])
        if key not in seen:
            seen.add(key)
            history.append({k: row.get(k) for k in ('id', 'product_id', 'platform', 'merchant_platform', 'final_price', 'base_price', 'price_kind', 'observed_at', 'reported_at', 'reference_only', 'url', 'title')})
    # Archive is append-only in the repository; browser history is rolling 365d.
    archive = DATA/'archive'/f'{now[:10]}.json'
    previous = load(archive, [])
    archive_keys = {(r['id'], r['observed_at']) for r in previous}
    previous.extend(r for r in list({o['id']:o for o in offers + references}.values()) if (r['id'], r['observed_at']) not in archive_keys)
    if previous:
        save(archive, previous)
    cutoff = (datetime.now(timezone.utc)-timedelta(days=365)).isoformat().replace('+00:00', 'Z')
    history = [r for r in history if r['observed_at'] >= cutoff]
    campaigns = [c for c in load(ROOT/'config/campaigns.json', []) if c.get('source_url') and active(c.get('starts_at'), c.get('ends_at'))]
    save(DATA/'catalog.json', products)
    save(DATA/'current.json', {'updated_at': now, 'offers': offers, 'reference_offers': references, 'statuses': statuses, 'campaigns': campaigns,
                             'coverage': '仅已采集来源；不代表全平台最低价', 'campaign_year': datetime.now(timezone.utc).year})
    save(DATA/'history.json', history)
    print(json.dumps({'offers': len(offers), 'sources': len(statuses), 'ok': sum(s['status']=='ok' for s in statuses)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
