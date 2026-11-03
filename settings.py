"""Shared distance policy for Local search, Directions checks and templates."""

DELIVERY_LIMIT_METERS = 10_000


def distance_policy():
    return {
        "limit_meters": DELIVERY_LIMIT_METERS,
        "limit_label": f"{DELIVERY_LIMIT_METERS / 1000:g}km",
        "limit_meters_label": f"{DELIVERY_LIMIT_METERS:,}m",
    }
