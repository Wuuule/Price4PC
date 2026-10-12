import sys
from pathlib import Path
from datetime import datetime, timezone
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from pricing import calculate, active

NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)

def coupon(**values):
    return {'type':'amount', 'value':100, 'verified':True, 'public':True,
            'evidence_url':'https://item.jd.com/123.html', 'label':'满减', **values}

class PricingTests(unittest.TestCase):
    def test_sequential_threshold_and_shipping(self):
        result = calculate(1000, [coupon(value=100,order=1),coupon(label='9折',type='rate',value=.9,order=2,threshold=900)], shipping=10, now=NOW)
        self.assertEqual(result['final_price'],820)
        self.assertEqual(len(result['applied_discounts']),2)
    def test_personal_unverified_expired_and_future_coupons_excluded(self):
        rows = [coupon(public=False),coupon(verified=False),coupon(ends_at='2026-10-11T00:00:00Z'),coupon(starts_at='2026-10-13T00:00:00Z')]
        result=calculate(1000,rows,now=NOW)
        self.assertEqual(result['final_price'],1000)
        self.assertEqual(len(result['excluded_discounts']),4)
    def test_incompatible_coupons_and_post_discount_threshold(self):
        rows=[coupon(group='shop'),coupon(group='shop'),coupon(threshold=950)]
        self.assertEqual(calculate(1000,rows,now=NOW)['final_price'],900)
    def test_discount_cap_and_cent_rounding(self):
        self.assertEqual(calculate('1999.99',[coupon(type='rate',value=.9,cap=100)],now=NOW)['final_price'],1899.99)
    def test_bad_money_and_rate(self):
        for value in [-1,'NaN','Infinity']:
            with self.assertRaises(ValueError): calculate(value)
        with self.assertRaises(ValueError): calculate(1000,[coupon(type='rate',value=1.1)])
    def test_timezone_required(self):
        with self.assertRaises(ValueError): active('2026-10-12',now=NOW)
    def test_no_coupon_evidence(self):
        self.assertEqual(calculate(1000,[coupon(evidence_url='')])['final_price'],1000)
