"""Production eligibility is separate from refunded shipping charges.

These statuses do not override cancellation, item changes, fulfillment,
quantity review, dismissal, or duplicate-production checks.
"""
PRODUCTION_PAYMENT_STATUSES=('paid','partially_refunded')


def payment_allows_production(order):
    return order.financial_status in PRODUCTION_PAYMENT_STATUSES
