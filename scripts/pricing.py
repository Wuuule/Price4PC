"""Deterministic price calculation. All amounts in CNY, no inferred coupons."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone


def money(value):
    value = Decimal(str(value))
    if not value.is_finite() or value < 0:
        raise ValueError('Invalid money')
    return value


def active(start=None, end=None, now=None):
    now = now or datetime.now(timezone.utc)
    def parse(value):
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('Dates must include timezone')
        return result
    return (not start or parse(start) <= now) and (not end or now < parse(end))


def calculate(base_price, coupons=(), shipping=0, now=None):
    """Sequential documented discounts; threshold tested at each specified step.

    Unverified, conditional-personal and expired discounts are never applied.
    A single coupon per exclusive group is allowed; alternatives must be supplied
    as separate offers, preventing accidental stacking of incompatible coupons.
    """
    total = money(base_price)
    used, excluded, groups = [], [], set()
    for coupon in sorted(coupons, key=lambda c: c.get('order', 0)):
        group = coupon.get('group')
        if (not coupon.get('verified') or not coupon.get('public', False)
                or not coupon.get('evidence_url')
                or not active(coupon.get('starts_at'), coupon.get('ends_at'), now)
                or total < money(coupon.get('threshold', 0))
                or (group and group in groups)):
            excluded.append(coupon.get('label', '未确认优惠'))
            continue
        before = total
        if coupon['type'] == 'amount':
            total -= money(coupon['value'])
        elif coupon['type'] == 'rate':
            rate = money(coupon['value'])
            if rate > 1:
                raise ValueError('Rate must be 0..1')
            reduction = total * (1 - rate)
            if coupon.get('cap') is not None:
                reduction = min(reduction, money(coupon['cap']))
            total -= reduction
        else:
            raise ValueError('Unsupported discount type')
        total = max(Decimal(0), total).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        if group:
            groups.add(group)
        used.append({'label': coupon.get('label', '优惠'), 'saving': float(before-total),
                     'evidence_url': coupon['evidence_url']})
    total += money(shipping)
    return {'final_price': float(total.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)),
            'applied_discounts': used, 'excluded_discounts': excluded}
