# Утренний план дня (кафе и фудтрак): вчера, что обычно бывает в этот день недели, погода, мероприятия.
import hashlib, html, json, os, urllib.parse
from datetime import date, datetime, timedelta

import daily_report as d
import events as ev
import weather

SITES = {"cafe": ("☕ Кафе", d.BASE), "truck": ("🚚 Трак", "https://gussi-penza-fud-trak.iiko.it/resto/api")}


def load(kind, today):
    base = SITES[kind][1]
    if kind == "truck":
        import foodtruck_report
        key = foodtruck_report.login()
    else:
        key = d.get(base + "/auth?" + urllib.parse.urlencode({"login": d.LOGIN, "pass": hashlib.sha1(os.environ["IIKO_PASSWORD"].encode()).hexdigest()})).strip()
    try:
        body = json.dumps({"reportType": "SALES", "buildSummary": "false", "groupByRowFields": ["OpenDate.Typed", "HourOpen"],
                           "aggregateFields": ["DishDiscountSumInt", "UniqOrderId.OrdersCount"],
                           "filters": {"OpenDate.Typed": {"filterType": "DateRange", "periodType": "CUSTOM", "from": (today - timedelta(days=42)).isoformat(),
                                                          "to": today.isoformat(), "includeLow": "true", "includeHigh": "false"}}}).encode()
        return json.loads(d.get(base + "/v2/reports/olap?key=" + key, body)).get("data", [])
    finally:
        d.get(base + "/logout?key=" + key)


BLOCKS = [("до 10:00", 0, 10), ("10–14", 10, 14), ("14–18", 14, 18), ("после 18:00", 18, 24)]


def build(kind, now, rows, fmt="plain"):
    today = now.date()
    title, _ = SITES[kind]
    days = {}
    for r in rows:
        days.setdefault(r["OpenDate.Typed"], {})[int(r["HourOpen"])] = (r["DishDiscountSumInt"], r["UniqOrderId.OrdersCount"])
    tot = {k: sum(v[0] for v in h.values()) for k, h in days.items()}
    tot = {k: v for k, v in tot.items() if v >= ev.MIN_REVENUE}
    out = ["%s · Утро, %s, %d %s" % (title, d.WEEKDAYS[today.weekday()], today.day, d.MONTHS[today.month - 1]), ""]
    todays = ev.on(today) if kind == "truck" else []
    if todays:
        out += [ev.line(today, "Сегодня на Арене Дизель"), ""]
    # на каких днях строим прогноз
    stat, label = None, ""
    for k in sorted({e["type"] for e in todays}):
        stat = ev.stats(k, tot, today)
        if stat:
            base, label = stat["days"][-6:], "прошлые дни с таким же мероприятием (%d)" % len(stat["days"][-6:])
            break
    if not stat:
        if kind == "cafe":
            base = [k for k in ((today - timedelta(days=7 * i)).isoformat() for i in range(1, 5)) if k in tot]
            label = "такие же дни недели, последние %d" % len(base)
        else:
            base = [k for k in sorted(tot) if k < today.isoformat() and not ev.on(date.fromisoformat(k))][-6:]
            label = "обычные дни без мероприятий, последние %d" % len(base)
    wx = None
    for _ in range(3):
        wx = weather.today_weather(now.replace(hour=min(now.hour, 9)))
        if wx:
            break
    if not base:
        out.append("Для прогноза пока мало данных.")
    else:
        rev = sum(tot[k] for k in base) / len(base)
        n = sum(sum(v[1] for v in days[k].values()) for k in base) / len(base)
        f = wx["factor"] if wx else 1.0
        out += ["Прогноз на день (по данным: %s)" % label,
                "Выручка: около %s%s" % (d.rub(rev * f), " (с поправкой на погоду %s)" % d.pct(rev * f, rev).replace("к ", "") if f < 1 else ""),
                "Чеков: около %d · средний чек около %s" % (round(n * f), d.rub(rev / n))]
        prof = {}
        for k in base:
            for h, v in days[k].items():
                prof[h] = prof.get(h, 0) + v[0]
        allv = sum(prof.values()) or 1
        out += ["", "Поток по времени (доля выручки)"]
        for name, lo, hi in BLOCKS:
            share = sum(v for h, v in prof.items() if lo <= h < hi) / allv * 100
            if share >= 1:
                out.append("%s: %.0f%%" % (name, share))
        top = sorted(sorted(prof, key=lambda h: -prof[h])[:2])
        out.append("Главные часы: " + ", ".join("%02d:00" % h for h in top))
        if todays and not stat:
            out += ["", "По таким мероприятиям истории пока нет: прогноз без поправки на мероприятие."]
        if stat:
            out += ["", "В такие дни выручка в среднем в %.1f раза выше обычных. Готовьте запас заранее." % stat["mult"]]
    if wx:
        out += ["", wx["line"]]
        tip = weather.drink_tip(wx)
        if tip:
            out.append("💡 " + tip)
    if kind == "truck":
        ahead = [(n, ev.on(today + timedelta(days=n))) for n in range(1, 8)]
        ahead = [(n, es) for n, es in ahead if es]
        out += ["", "🏟 Афиша Арены Дизель на неделю"]
        if ahead:
            for n, es in ahead:
                dd = today + timedelta(days=n)
                out.append("• %s, %d.%02d: %s" % (d.WEEKDAYS[dd.weekday()][:2].capitalize(), dd.day, dd.month, "; ".join(ev.text(e) for e in es)))
        else:
            out.append("Ближайшие 7 дней мероприятий нет.")
    text = "\n".join(out)
    return html.escape(text) if fmt == "html" else text


if __name__ == "__main__":
    import sys
    k = sys.argv[1] if len(sys.argv) > 1 else "cafe"
    n = datetime.now(d.MSK)
    print(build(k, n, load(k, n.date())))
