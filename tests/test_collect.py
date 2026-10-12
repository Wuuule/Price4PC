import sys
import json
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from collect import matches, parse_page, parse_price, allowed_url, validate_feed, page_status
ROOT=Path(__file__).resolve().parents[1]
PRODUCTS=json.loads((ROOT/'config/products.json').read_text())
NOW='2026-10-12T02:00:00Z'

def product(id): return next(p for p in PRODUCTS if p['id']==id)

class ParserTests(unittest.TestCase):
    def test_model_boundaries_and_wrong_sku(self):
        p=product('9700x')
        self.assertTrue(matches('AMD 锐龙7 9700X 盒装CPU',p))
        for name in ['AMD 9700X3D CPU','AMD 9700X 主板套装','AMD 9700X 电脑主机','AMD 9700X/7800X3D CPU','AMD 9700X 二手']:
            self.assertFalse(matches(name,p),name)
    def test_ram_single_stick_required(self):
        p=product('ddr5-16gb')
        self.assertTrue(matches('金士顿 DDR5 16GB 单条 台式机内存',p))
        for name in ['DDR5 16GB 套装','DDR5 16GBx2','DDR5 16GB 单条 笔记本','DDR5 32GB 单条','DDR5 16GB']:
            self.assertFalse(matches(name,p),name)
    def test_ssd_exact_interface_and_capacity(self):
        p=product('nvme-gen4-1tb')
        self.assertTrue(matches('NVMe PCIe4.0 1TB M.2 固态硬盘',p))
        self.assertFalse(matches('NVMe PCIe3.0 1TB M.2 固态硬盘',p))
        self.assertFalse(matches('NVMe PCIe4.0 2TB M.2 固态硬盘',p))
    def test_price_ranges_and_installments_are_not_prices(self):
        self.assertEqual(parse_price('￥1,299.99'),1299.99)
        self.assertEqual(parse_price('1299元（需用券）'),1299)
        for text in ['1299起','1299-1999','每期129元','$199','20%','定金99']:
            self.assertIsNone(parse_price(text),text)
    def test_jd_fixture_binds_title_to_own_card_price(self):
        html='''<ul><li class="gl-item"><div class="p-name"><a href="//item.jd.com/12345.html">AMD 9700X 盒装CPU</a></div><div class="p-price"><i>1800.00</i></div></li><li class="gl-item"><div class="p-name"><a href="//item.jd.com/99999.html">AMD 9700X 主板套装</a></div><div class="p-price"><i>100</i></div></li></ul>'''
        rows=parse_page(html,'jd',product('9700x'),'https://search.jd.com/',NOW)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['final_price'],1800)
        self.assertEqual(rows[0]['url'],'https://item.jd.com/12345.html')
        self.assertEqual(rows[0]['price_kind'],'listed')
    def test_jsonld_aggregate_and_out_of_stock_excluded(self):
        def html(kind,stock):
            return '<script type="application/ld+json">'+json.dumps({'@type':'Product','name':'AMD 9700X CPU','offers':{'@type':kind,'priceCurrency':'CNY','price':'1800','availability':'https://schema.org/'+stock}})+'</script>'
        url='https://item.jd.com/123.html'
        self.assertEqual(len(parse_page(html('Offer','InStock'),'jd',product('9700x'),url,NOW)),1)
        self.assertEqual(parse_page(html('Offer','OutOfStock'),'jd',product('9700x'),url,NOW),[])
        self.assertEqual(parse_page(html('AggregateOffer','InStock'),'jd',product('9700x'),url,NOW),[])
    def test_platform_url_validation(self):
        self.assertFalse(allowed_url('https://jd.com.evil.test/123',('jd.com',)))
        self.assertFalse(allowed_url('javascript:alert(1)',('jd.com',)))
        self.assertTrue(allowed_url('https://item.jd.com/123.html',('jd.com',)))
    def test_status_login_and_blocked(self):
        self.assertEqual(page_status('请登录后查看',[])[0],'login_required')
        self.assertEqual(page_status('安全验证',[])[0],'blocked')
    def test_feed_requires_recent_specific_sku_and_shipping(self):
        row={'product_id':'9700x','platform':'jd','currency':'CNY','in_stock':True,'sku_confirmed':True,'observed_at':'2026-10-12T01:00:00Z','evidence_url':'https://item.jd.com/123.html','url':'https://item.jd.com/123.html','title':'AMD 9700X CPU','base_price':1900,'shipping':0,'coupons':[]}
        self.assertEqual(validate_feed(row,PRODUCTS,NOW)['price_kind'],'calculated')
        with self.assertRaises(ValueError): validate_feed({**row,'shipping':None},PRODUCTS,NOW)
        with self.assertRaises(ValueError): validate_feed({**row,'observed_at':'2026-09-01T00:00:00Z'},PRODUCTS,NOW)
        with self.assertRaises(ValueError): validate_feed({**row,'sku_confirmed':False},PRODUCTS,NOW)
