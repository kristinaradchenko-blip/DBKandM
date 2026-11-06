# Ежедневная сводка по фудтраку Gussi (только чтение). Запуск: python3 foodtruck_report.py [ГГГГ-ММ-ДД] [--telegram]
import hashlib, html, json, os, sys, urllib.parse
from datetime import date, timedelta

import daily_report as d
import weather
import events as ev

BASE = "https://gussi-penza-fud-trak.iiko.it/resto/api"
WD = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def creds():
    """Учётка фудтрака (IIKO_TRUCK_USER/IIKO_TRUCK_PASSWORD); если не заданы, прежняя Kris."""
    u, p = os.environ.get("IIKO_TRUCK_USER"), os.environ.get("IIKO_TRUCK_PASSWORD")
    return (u, p) if u and p else (d.LOGIN, os.environ.get("IIKO_PASSWORD"))


def login():
    u, p = creds()
    return d.get(BASE + "/auth?" + urllib.parse.urlencode({"login": u, "pass": hashlib.sha1(p.encode()).hexdigest()})).strip()


def olap(key, by, aggs, start, end):
    body = json.dumps({"reportType": "SALES", "buildSummary": "false", "groupByRowFields": by, "aggregateFields": aggs,
                       "filters": {"OpenDate.Typed": {"filterType": "DateRange", "periodType": "CUSTOM", "from": start.isoformat(),
                                                      "to": end.isoformat(), "includeLow": "true", "includeHigh": "false"}}}).encode()
    return json.loads(d.get(BASE + "/v2/reports/olap?key=" + key, body)).get("data", [])


def load(day):
    key = login()
    try:
        nxt = day + timedelta(days=1)
        return {"days": olap(key, ["OpenDate.Typed"], ["DishDiscountSumInt", "UniqOrderId.OrdersCount", "DiscountSum"], day - timedelta(days=28), nxt),
                "hours": olap(key, ["HourOpen"], ["DishDiscountSumInt", "UniqOrderId.OrdersCount"], day, nxt),
                "dishes": olap(key, ["DishGroup", "DishName"], ["DishDiscountSumInt", "DishAmountInt"], day, nxt),
                "disc": olap(key, ["UniqOrderId.Id", "OrderDiscount.Type"], ["DiscountSum", "DishSumInt"], day, nxt),
                "opens": d.attendance_starts(BASE, key, day)}
    finally:
        d.get(BASE + "/logout?key=" + key)


def build(day, data, fmt="plain", events=True):
    by = {r["OpenDate.Typed"]: r for r in data["days"]}
    cur = by.get(day.isoformat())
    out = ["🚚 Трак · %s, %s, %d.%02d" % ("Итоги дня" if day == date.today() else "Сводка за дату", WD[day.weekday()], day.day, day.month)]
    if not cur or not cur["DishDiscountSumInt"]:
        out += ["", "Продаж за этот день нет (фудтрак не работал или касса не передала данные)."]
    else:
        rev, n = cur["DishDiscountSumInt"], cur["UniqOrderId.OrdersCount"]
        same = [by[(day - timedelta(days=7 * i)).isoformat()] for i in range(1, 5) if (day - timedelta(days=7 * i)).isoformat() in by
                and by[(day - timedelta(days=7 * i)).isoformat()]["DishDiscountSumInt"] > 0]
        out += ["", "Выручка: %s%s" % (d.rub(rev), " (%s к прошлой неделе)" % d.pct(rev, same[0]["DishDiscountSumInt"]) if same and (day - timedelta(days=7)).isoformat() == same[0]["OpenDate.Typed"] else ""),
                "Чеков: %d · средний чек %s" % (n, d.rub(rev / n))]
        start = d.first_open(data.get("opens", []), day)
        if start:
            out.insert(len(out) - 0, "Начало работы: %s (вход в систему)" % start)
        if len(same) > 1:
            avg = sum(r["DishDiscountSumInt"] for r in same) / len(same)
            out.append("Обычно в такой день недели: %s (%s)" % (d.rub(avg), d.pct(rev, avg)))
        hrs = sorted(data["hours"], key=lambda r: -r["DishDiscountSumInt"])[:2]
        if hrs:
            out.append("Пик: " + ", ".join("%02d:00 (%s)" % (int(r["HourOpen"]), d.rub(r["DishDiscountSumInt"])) for r in sorted(hrs, key=lambda r: int(r["HourOpen"]))))
        disc = cur.get("DiscountSum") or 0
        if disc:
            out.append("Скидки: %s (%.0f%% от выручки до скидок)" % (d.rub(disc), disc / (rev + disc) * 100))
            # Чеки со скидкой, сгруппированные по размеру скидки в чеке (округляем до 10%), как в кофейне
            buckets = {}
            for r in data.get("disc", []):
                if (r["DiscountSum"] or 0) > 0 and r["DishSumInt"]:
                    pc = max(10, int(r["DiscountSum"] / r["DishSumInt"] * 10 + 0.5) * 10)
                    b_ = buckets.setdefault(pc, {"n": 0, "sum": 0, "types": {}})
                    b_["n"] += 1
                    b_["sum"] += r["DiscountSum"]
                    name = r["OrderDiscount.Type"] or "без названия"
                    b_["types"][name] = b_["types"].get(name, 0) + 1
            for pc in sorted(buckets):
                b_ = buckets[pc]
                top_types = ", ".join(k for k, _ in sorted(b_["types"].items(), key=lambda kv: -kv[1])[:2])
                out.append("• %d%% — %d %s · %s (%s)" % (pc, b_["n"], d.chk_word(b_["n"]), d.rub(b_["sum"]), top_types))
        items = [r for r in data["dishes"] if r["DishName"] != d.FREE_PRICE and r["DishDiscountSumInt"] > 0]
        free = [r for r in data["dishes"] if r["DishName"] == d.FREE_PRICE]
        if items:
            out += ["", "Что продавали"]
            for i, r in enumerate(sorted(items, key=lambda r: -r["DishDiscountSumInt"])[:5], 1):
                out.append("%d. %s — %d шт · %s" % (i, r["DishName"].strip(), r["DishAmountInt"], d.rub(r["DishDiscountSumInt"])))
        if free and free[0]["DishDiscountSumInt"]:
            out.append("«Свободная цена»: %d шт на %s (%.0f%% выручки), позиции не видны" % (free[0]["DishAmountInt"], d.rub(free[0]["DishDiscountSumInt"]), free[0]["DishDiscountSumInt"] / rev * 100))
    if events:
        today_ev = ev.line(day, "Сегодня было мероприятие на Арене Дизель")
        if today_ev:
            out.insert(2, today_ev)
            tot = ev.totals([{"OpenDate.Typed": r["OpenDate.Typed"], "DishDiscountSumInt": r["DishDiscountSumInt"]} for r in data["days"]])
            for k in ev.kinds(day):
                st = ev.stats(k, tot, day)
                if st and cur and cur["DishDiscountSumInt"]:
                    out.insert(3, "В прошлые такие дни (%d) выручка в среднем %s" % (len(st["days"]), d.rub(st["avg"])))
                    break
        ahead = [(n, ev.on(day + timedelta(days=n))) for n in (1,)]
        ahead = [(n, es) for n, es in ahead if es]
        if ahead:
            tot = ev.totals([{"OpenDate.Typed": r["OpenDate.Typed"], "DishDiscountSumInt": r["DishDiscountSumInt"]} for r in data["days"]])
            out += ["", "⚠️ Обратите внимание"]
            for n, es in ahead:
                when = {1: "Завтра", 2: "Послезавтра", 3: "Через 3 дня"}[n]
                dd = day + timedelta(days=n)
                out.append("• %s (%s, %d.%02d) на Арене Дизель: %s." % (when, WD[dd.weekday()], dd.day, dd.month, "; ".join(ev.text(e) for e in es)))
                for k in sorted({e["type"] for e in es}):
                    st = ev.stats(k, tot, day + timedelta(days=1))
                    if st:
                        out.append("  В прошлые такие дни (%d) выручка была в среднем %s, примерно в %.1f раза выше обычных дней. Заранее проверьте запас продуктов и стаканов." % (len(st["days"]), d.rub(st["avg"]), st["mult"]))
                        break
    text = "\n".join(out)
    return html.escape(text) if fmt == "html" else text


def load_now(today):
    key = login()
    try:
        nxt = today + timedelta(days=1)
        return {"hours": olap(key, ["OpenDate.Typed", "HourOpen"], ["DishDiscountSumInt", "UniqOrderId.OrdersCount"], today - timedelta(days=21), nxt),
                "dishes": olap(key, ["DishName"], ["DishDiscountSumInt", "DishAmountInt"], today, nxt),
                "opens": d.attendance_starts(BASE, key, today)}
    finally:
        d.get(BASE + "/logout?key=" + key)


def build_now(now, data, fmt="plain", events=True):
    """Промежуточный отчёт по фудтраку: итоги за полные часы и сравнение с обычными днями."""
    today, H = now.date(), now.hour
    days = {}
    for r in data["hours"]:
        days.setdefault(r["OpenDate.Typed"], {})[int(r["HourOpen"])] = r
    head = "⏱ Трак · День, сейчас %02d:%02d, %s" % (now.hour, now.minute, WD[today.weekday()])

    def part(day, upto, field):
        return sum(r[field] for h, r in days.get(day, {}).items() if h < upto)

    out = [head, ""]
    rev, n = part(today.isoformat(), H, "DishDiscountSumInt"), part(today.isoformat(), H, "UniqOrderId.OrdersCount")
    if H < 9:
        out.append("Пока рано: за первые часы данных мало. Попробуйте после 10:00.")
    else:
        out += ["С открытия до %02d:00 (полные часы)" % H, "Выручка: %s · чеков %d%s" % (d.rub(rev), n, " · средний чек %s" % d.rub(rev / n) if n else "")]
        start = d.first_open(data.get("opens", []), today)
        out.append("Начало работы: %s (вход в систему)" % start if start else "Начало работы: сегодня входов в систему ещё не было")
        past = [k for k in sorted(days) if k < today.isoformat() and sum(r["DishDiscountSumInt"] for r in days[k].values()) > 0][-7:]
        label, stat, tips = "последние %d рабочих дней", None, []
        if events:
            tot = ev.totals(data["hours"])
            tkinds = ev.kinds(today)
            if tkinds:
                out.insert(2, ev.line(today, "Сегодня на Арене Дизель"))
                for k in tkinds:
                    stat = ev.stats(k, tot, today)
                    if stat:
                        past, label = stat["days"][-7:], "прошлые дни с таким же мероприятием (%d)"
                        break
                if not stat:
                    tips.append("По таким мероприятиям в истории фудтрака пока нет данных, прогноз без поправки на мероприятие: ориентируйтесь на ситуацию на месте.")
            else:
                skip = ev.big_days(tot, today)
                past = [k for k in past if k not in skip] or past
        if past:
            full = [sum(r["DishDiscountSumInt"] for r in days[k].values()) for k in past]
            upto = [part(k, H, "DishDiscountSumInt") for k in past]
            ua, fa = sum(upto) / len(past), sum(full) / len(past)
            out += ["", "Для сравнения: " + label % len(past),
                    "К этому часу обычно %s (сейчас %s)" % (d.rub(ua), d.pct(rev, ua) if ua else "—"),
                    "За весь день обычно %s" % d.rub(fa),
                    "Оценка на конец дня: около %s" % d.rub(max(rev, rev + max(fa - ua, 0)))]
            wx = weather.today_weather(now)
            if wx:
                if wx["factor"] < 1:
                    est = rev + max(fa - ua, 0) * wx["factor"]
                    out[-1] = "Оценка на конец дня: около %s (с поправкой на погоду %s)" % (d.rub(max(rev, est)), d.pct(est, rev + max(fa - ua, 0)).replace("к ", ""))
                out.append(wx["line"])
                wtip = weather.drink_tip(wx)
                if wtip:
                    out.append("💡 " + wtip)
            if stat:
                prof = {}
                for k in past:
                    for h, r in days[k].items():
                        prof[h] = prof.get(h, 0) + r["DishDiscountSumInt"]
                top = sorted(sorted(prof, key=lambda h: -prof[h])[:2])
                tips.append("В такие дни выручка в среднем в %.1f раза выше обычных дней, главные часы: %s. Готовьте запас заранее и держите самые быстрые позиции под рукой." % (stat["mult"], ", ".join("%02d:00" % h for h in top)))
            out += ["💡 " + t for t in tips]
            out += ["Выручка фудтрака сильно зависит от мероприятий и погоды, оценка грубая."]
        items = [r for r in data["dishes"] if r["DishName"] != d.FREE_PRICE and r["DishDiscountSumInt"] > 0]
        if items:
            out += ["", "Сегодня лучше всего идут"]
            for i, r in enumerate(sorted(items, key=lambda r: -r["DishDiscountSumInt"])[:3], 1):
                out.append("%d. %s — %d шт · %s" % (i, r["DishName"].strip(), r["DishAmountInt"], d.rub(r["DishDiscountSumInt"])))
    text = "\n".join(out)
    return html.escape(text) if fmt == "html" else text


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--now" in sys.argv:
        now = d.datetime.now(d.MSK)
        print(build_now(now, load_now(now.date()), "html" if "--telegram" in sys.argv else "plain"))
        sys.exit()
    day = date.fromisoformat(args[0]) if args else date.today() - timedelta(days=1)
    print(build(day, load(day), "html" if "--telegram" in sys.argv else "plain"))
