import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from collect import offer, matches, load, ROOT, page_status
from secondary import parse_detail, recent_report, discover
PRODUCTS=load(ROOT/'config/products.json', [])
NOW='2026-10-12T02:00:00Z'

def detail(timestamp='2026-10-11 12:00:00 +0800', status=''):
    return f'''<meta name="weibo:webpage:update_at" content="{timestamp}"><div class="info-right"><div class="title-box"><h1>华硕 RX9070XT 16GB 显卡{status}</h1><span class="price-large">7299元</span></div><span class="time">10-11 12:00</span><span class="mall">京东</span><span class="price-desc">需用券</span></div><aside><span class="price-large">1999元</span></aside>'''

class SecondaryTests(unittest.TestCase):
    def test_detail_own_price_timestamp_and_platform(self):
        rows=parse_detail(detail(),'https://www.smzdm.com/p/123/',PRODUCTS,NOW,offer)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['final_price'],7299)
        self.assertEqual(rows[0]['reported_at'],'2026-10-11T04:00:00Z')
        self.assertEqual(rows[0]['merchant_platform'],'jd')
        self.assertFalse(rows[0]['reference_only'])
    def test_old_sold_out_and_unknown_dates_not_current_prices(self):
        for html in [detail('2026-09-22 12:00:00 +0800'),detail(status='售罄'),detail('unknown')]:
            row=parse_detail(html,'https://www.smzdm.com/p/123/',PRODUCTS,NOW,offer)[0]
            self.assertTrue(row['reference_only'])
            self.assertFalse(recent_report(row,NOW))
    def test_future_timestamp_not_current(self):
        row=parse_detail(detail('2026-10-13 12:00:00 +0800'),'https://www.smzdm.com/p/123/',PRODUCTS,NOW,offer)[0]
        self.assertTrue(row['reference_only'])
    def test_discovery_excludes_ambiguous_variants(self):
        html='''<div class="haojia-card-container"><a class="card-right-box-title" href="https://www.smzdm.com/p/123/">华硕 RTX5070Ti 16GB 显卡</a></div><div class="haojia-card-container"><a class="card-right-box-title" href="https://www.smzdm.com/p/124/">RTX5060 5070 ti 显卡 RTX5060 8G</a></div>'''
        self.assertEqual(discover(html,'https://www.smzdm.com/fenlei/xianka/',PRODUCTS,matches),{'https://www.smzdm.com/p/123/'})
    def test_script_only_captcha_detected(self):
        self.assertEqual(page_status('<script>new TencentCaptcha()</script>',[])[0],'blocked')
    def test_270k_plus_not_substituted(self):
        p=next(p for p in PRODUCTS if p['id']=='ultra7-270k')
        self.assertFalse(matches('Intel Ultra 7 270K Plus CPU',p))
