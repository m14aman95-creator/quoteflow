"""Subscription plans. Billing is stubbed: plan limits are enforced, payment is not built."""

PLANS = {
    "free": {"name": "Free", "price_bhd": 0, "quotes_per_month": 5, "users": 1},
    "starter": {"name": "Starter", "price_bhd": 5, "quotes_per_month": 30, "users": 1},
    "professional": {"name": "Professional", "price_bhd": 12, "quotes_per_month": 150, "users": 3},
    "business": {"name": "Business", "price_bhd": 25, "quotes_per_month": 500, "users": 8},
}


def plan_limit(plan: str) -> int:
    return PLANS.get(plan, PLANS["free"])["quotes_per_month"]
