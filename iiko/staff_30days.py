# Кто пробивал чеки за последние 30 дней: сотрудники, чеки, средний чек, в какие дни (только чтение).
import getpass, hashlib, json, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import date, timedelta

HOSTS = ["https://gussi-penza.iiko.it/resto/api", "https://gussi-penza-fud-trak.iiko.it/resto/api"]
LOGIN = "Kris"
DAYS = 30


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
    for base in HOSTS:
        key = None
        try:
            key = get(base + "/auth?" + urllib.parse.urlencode({"login": LOGIN, "pass": h})).strip()
            body = json.dumps({"reportType": "SALES", "buildSummary": "false",
                               "groupByRowFields": ["Department", "Cashier", "Cashier.Code", "OpenDate.Typed"],
                               "aggregateFields": ["DishDiscountSumInt", "UniqOrderId.OrdersCount"],
                               "filters": {"OpenDate.Typed": {"filterType": "DateRange", "periodType": "CUSTOM",
                                                              "from": start, "to": end,
                                                              "includeLow": "true", "includeHigh": "false"}}}).encode()
            rows = json.loads(get(base + "/v2/reports/olap?key=" + key, body)).get("data", [])
            agg = defaultdict(lambda: {"o": 0, "t": 0, "days": set()})
            for r in rows:
                o = r.get("UniqOrderId.OrdersCount") or 0
                if not o:
                    continue
                k = (r.get("Department"), r.get("Cashier") or "(не указан)", r.get("Cashier.Code"))
                a = agg[k]
                a["o"] += o
                a["t"] += r.get("DishDiscountSumInt") or 0
                a["days"].add(r.get("OpenDate.Typed"))
            print("=== " + base.split("//")[1].split("/")[0] + "  (строк в отчёте: %d)" % len(rows))
            print("%-20s %-18s %5s %7s %10s %8s  %s" % ("Заведение", "Кассир", "Код", "Чеков", "Выручка", "Ср.чек", "Дней / первый .. последний"))
            for k, a in sorted(agg.items(), key=lambda kv: -kv[1]["o"]):
                d = sorted(x for x in a["days"] if x)
                print("%-20s %-18s %5s %7d %10d %8d  %d / %s .. %s" % (k[0], k[1][:18], k[2], a["o"], a["t"], a["t"] / a["o"], len(d), d[0] if d else "", d[-1] if d else ""))
            print()
        except Exception as e:
            print(base, "- ошибка:", e)
        finally:
            if key:
                try:
                    get(base + "/logout?key=" + key)
                except Exception:
                    pass
    print("Готово, из iiko вышли.")


main()
