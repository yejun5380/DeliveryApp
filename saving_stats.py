from datetime import timedelta


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
