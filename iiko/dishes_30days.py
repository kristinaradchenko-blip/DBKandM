# Статистика по блюдам за 30 дней: выручка, количество, себестоимость, маржа (только чтение).
import csv, getpass, hashlib, json, os, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import date, timedelta

HOSTS = ["https://gussi-penza.iiko.it/resto/api", "https://gussi-penza-fud-trak.iiko.it/resto/api"]
LOGIN = "Kris"
DAYS = 30
TOP = 15


def get(url, data=None):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(2)


def main():
    h = hashlib.sha1(getpass.getpass("Пароль Kris (на экране не виден): ").encode()).hexdigest()
    start = (date.today() - timedelta(days=DAYS - 1)).isoformat()
    end = (date.today() + timedelta(days=1)).isoformat()
    print("Период: %s .. сегодня включительно\n" % start)
    allrows = []
    for base in HOSTS:
        key = None
        try:
            key = get(base + "/auth?" + urllib.parse.urlencode({"login": LOGIN, "pass": h})).strip()
            cols = json.loads(get(base + "/v2/reports/olap/columns?reportType=SALES&key=" + key))
            qty = "DishAmountInt" if "DishAmountInt" in cols else None
            grp = "DishGroup" if "DishGroup" in cols else None
            aggs = ["DishDiscountSumInt", "ProductCostBase.ProductCost"] + ([qty] if qty else [])
            rows_by = ["Department"] + ([grp] if grp else []) + ["DishName"]
            body = json.dumps({"reportType": "SALES", "buildSummary": "false",
                               "groupByRowFields": rows_by, "aggregateFields": aggs,
                               "filters": {"OpenDate.Typed": {"filterType": "DateRange", "periodType": "CUSTOM",
                                                              "from": start, "to": end,
                                                              "includeLow": "true", "includeHigh": "false"}}}).encode()
            data = json.loads(get(base + "/v2/reports/olap?key=" + key, body)).get("data", [])
            for r in data:
                rev = r.get("DishDiscountSumInt") or 0
                if rev <= 0:
                    continue
                cost = r.get("ProductCostBase.ProductCost") or 0
                allrows.append({"dep": r.get("Department"), "group": (r.get(grp) if grp else "") or "", "dish": r.get("DishName"),
                                "qty": (r.get(qty) or 0) if qty else 0, "rev": rev, "cost": cost, "margin": rev - cost})
        except Exception as e:
            print(base, "- ошибка:", e)
        finally:
            if key:
                try:
                    get(base + "/logout?key=" + key)
                except Exception:
                    pass
    for dep in sorted(set(r["dep"] for r in allrows)):
        rs = [r for r in allrows if r["dep"] == dep]
        total = sum(r["rev"] for r in rs)
        print("=== %s: позиций с продажами %d, выручка %d" % (dep, len(rs), total))
        print("-- Топ по выручке")
        print("%-34s %6s %9s %9s %6s" % ("Блюдо", "Шт", "Выручка", "Маржа", "Доля"))
        for r in sorted(rs, key=lambda r: -r["rev"])[:TOP]:
            print("%-34s %6d %9d %9d %5.1f%%" % (str(r["dish"])[:34], r["qty"], r["rev"], r["margin"], 100.0 * r["rev"] / total))
        print("-- Топ по марже в рублях")
        for r in sorted(rs, key=lambda r: -r["margin"])[:10]:
            pct = 100.0 * r["margin"] / r["rev"] if r["rev"] else 0
            print("%-34s %6d %9d %9d  маржа %3.0f%%" % (str(r["dish"])[:34], r["qty"], r["rev"], r["margin"], pct))
        g = defaultdict(lambda: [0, 0, 0])
        for r in rs:
            a = g[r["group"] or "(без группы)"]
            a[0] += r["qty"]; a[1] += r["rev"]; a[2] += r["margin"]
        print("-- По группам блюд")
        for name, a in sorted(g.items(), key=lambda kv: -kv[1][1])[:12]:
            print("%-34s %6d %9d %9d %5.1f%%" % (name[:34], a[0], a[1], a[2], 100.0 * a[1] / total))
        print()
    path = os.path.expanduser("~/Desktop/iiko_dishes_30d.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Заведение", "Группа", "Блюдо", "Количество", "Выручка", "Себестоимость", "Маржа"])
        for r in sorted(allrows, key=lambda r: (r["dep"] or "", -r["rev"])):
            w.writerow([r["dep"], r["group"], r["dish"], r["qty"], round(r["rev"]), round(r["cost"]), round(r["margin"])])
    print("Полная таблица сохранена:", path)
    print("Готово, из iiko вышли.")


main()
