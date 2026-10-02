"""
Plan definitions — the one place to edit tiers and pricing.

Each plan has:
  devices   : the maximum number of devices an account on this plan may enroll
  name      : display name
  price     : display price (shown on the pricing page / panel)
  period    : display billing period ("" for free)
  stripe_env: the env var holding this plan's Stripe Price ID (None for free)

To change prices, edit `price` here (what customers see) and set the matching
Stripe Price ID via the environment (STRIPE_PRICE_PRO / STRIPE_PRICE_BUSINESS).
"""

import os

PLANS = {
    "free": {
        "name": "Free",
        "devices": 3,
        "price": "$0",
        "period": "",
        "stripe_env": None,
        "blurb": "For a couple of personal computers.",
    },
    "pro": {
        "name": "Pro",
        "devices": 10,
        "price": "$4.99",          # placeholder — edit here
        "period": "/mo",
        "stripe_env": "STRIPE_PRICE_PRO",
        "blurb": "For power users with several machines.",
    },
    "business": {
        "name": "Business",
        "devices": 50,
        "price": "$14.99",         # placeholder — edit here
        "period": "/mo",
        "stripe_env": "STRIPE_PRICE_BUSINESS",
        "blurb": "For teams and fleets of computers.",
    },
}

DEFAULT_PLAN = "free"
PAID_PLANS = ("pro", "business")


def device_limit(plan):
    """Max devices for a plan name (falls back to the free limit)."""
    return PLANS.get(plan, PLANS[DEFAULT_PLAN])["devices"]


def is_valid_plan(plan):
    return plan in PLANS


def can_schedule(plan):
    """Scheduled power actions are a paid-tier feature."""
    return plan in PAID_PLANS


def stripe_price_id(plan):
    """The configured Stripe Price ID for a paid plan, or None."""
    env = PLANS.get(plan, {}).get("stripe_env")
    return os.environ.get(env) if env else None


def plan_by_price_id(price_id):
    """Reverse lookup: which plan does a Stripe Price ID belong to?"""
    for name in PAID_PLANS:
        if stripe_price_id(name) == price_id:
            return name
    return None
