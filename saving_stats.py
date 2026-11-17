from datetime import timedelta
from decimal import Decimal


def menu_calorie_chart(rows):
    """Dependency-free donut segments; callers group by menu ID, never by name."""
    colors = ('#126748', '#2869a0', '#aa4c21', '#7951a1', '#80701b', '#237f82', '#ad3e66', '#52616b')
    items = []
    total = sum(max(0, int(row[3])) for row in rows)
    cumulative = 0
    for menu_id, name, restaurant, calories in rows:
        calories = max(0, int(calories))
        if not calories:
            continue
        start = Decimal(cumulative) * 100 / total
        cumulative += calories
        end = Decimal(cumulative) * 100 / total
        items.append(dict(menu_id=menu_id, name=name, restaurant=restaurant,
                          calories=calories, percent=f'{Decimal(calories)*100/total:.1f}',
                          color=colors[len(items) % len(colors)], start=f'{start:.6f}', end=f'{end:.6f}'))
    gradient = ', '.join(f"{item['color']} {item['start']}% {item['end']}%" for item in items)
    return dict(total=total, items=items, gradient=gradient)


def calorie_series(starts, rows):
    """Aggregate the same recent windows as money charts, preserving menu IDs."""
    series = {}
    for period, buckets in starts.items():
        menus = {}
        for day, menu_id, name, restaurant, calories in rows:
            if day < buckets[0]:
                continue
            if menu_id not in menus:
                menus[menu_id] = [menu_id, name, restaurant, 0]
            menus[menu_id][3] += int(calories)
        series[period] = menu_calorie_chart(sorted(menus.values(), key=lambda row: (-row[3], row[0])))
    return series


def period_starts(today):
    monday = today - timedelta(days=today.weekday())
    month_index = today.year * 12 + today.month - 1
    return {
        "daily": [today - timedelta(days=offset) for offset in range(6, -1, -1)],
        "weekly": [monday - timedelta(weeks=offset) for offset in range(7, -1, -1)],
        "monthly": [today.replace(year=index // 12, month=index % 12 + 1, day=1)
                    for index in range(month_index - 11, month_index + 1)],
    }


def saving_series(starts, daily_amounts):
    series = {}
    for period, buckets in starts.items():
        totals = dict.fromkeys(buckets, 0)
        for day, amount in daily_amounts:
            if period == "weekly":
                day -= timedelta(days=day.weekday())
            elif period == "monthly":
                day = day.replace(day=1)
            if day in totals:
                totals[day] += int(amount)
        peak = max(abs(amount) for amount in totals.values()) or 1
        rows = []
        for day, amount in totals.items():
            label = day.isoformat()
            if period == "weekly":
                label += f" ~ {day + timedelta(days=6):%m-%d}"
            elif period == "monthly":
                label = label[:7]
            rows.append(dict(label=label, amount=amount, width=abs(amount) * 100 / peak))
        series[period] = dict(rows=rows, total=sum(totals.values()), has_amount=any(totals.values()))
    return series
