# Мероприятия Арены Дизель (календарь в data/diesel_events.json) и их влияние на выручку фудтрака.
import json, os
from datetime import date, timedelta

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "diesel_events.json")
MIN_DAYS = 2        # сколько прошлых дней с таким мероприятием нужно, чтобы считать по истории
MIN_REVENUE = 3000  # день с меньшей выручкой считаем нерабочим
KIND_WORD = {"Домашний матч": "домашний матч «Дизеля»", "Матч": "матч хоккейной команды «Дизелист»"}


def _all():
    try:
        return json.load(open(PATH, encoding="utf-8"))
    except Exception:
        return []


def on(day):
    return [e for e in _all() if e["date"] == day.isoformat()]


def kinds(day):
    return sorted({e["type"] for e in on(day)})


def text(e):
    return "%s%s" % (e["name"], " в " + e["time"] if e.get("time") else "")


def line(day, prefix):
    ev = on(day)
    if not ev:
        return None
    return "🏟 %s: %s" % (prefix, "; ".join(text(e) for e in ev))


def totals(hours):
    """{дата: выручка} из строк OLAP по часам."""
    res = {}
    for r in hours:
        res[r["OpenDate.Typed"]] = res.get(r["OpenDate.Typed"], 0) + r["DishDiscountSumInt"]
    return {k: v for k, v in res.items() if v >= MIN_REVENUE}


def stats(kind, tot, before):
    """Что показывает история: (дни с таким мероприятием, кратность к дням без мероприятий) или None."""
    ev_days = [k for k in tot if k < before.isoformat() and kind in kinds(date.fromisoformat(k))]
    base = [v for k, v in tot.items() if k < before.isoformat() and not on(date.fromisoformat(k))]
    if len(ev_days) < MIN_DAYS or len(base) < 3:
        return None
    ev_avg = sum(tot[k] for k in ev_days) / len(ev_days)
    return {"days": ev_days, "avg": ev_avg, "mult": ev_avg / (sum(base) / len(base))}


def big_days(tot, before):
    """Дни, которые сильно отличаются из-за мероприятий (по истории), чтобы не портить обычное сравнение."""
    res = set()
    for kind in {e["type"] for e in _all()}:
        s = stats(kind, tot, before)
        if s and s["mult"] >= 1.5:
            res |= set(s["days"])
    return res
