# Поиск полей iiko, по которым можно разбить чеки по сотрудникам (только чтение).
import getpass, hashlib, json, time, urllib.parse, urllib.request
from datetime import date, timedelta

HOSTS = ["https://gussi-penza.iiko.it/resto/api", "https://gussi-penza-fud-trak.iiko.it/resto/api"]
LOGIN = "Kris"
KEYS = ("waiter", "cashier", "user", "employee", "auth", "role", "staff", "team", "session", "worker", "personal", "manager")


def get(url, data=None):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(2)


def main():
    h = hashlib.sha1(getpass.getpass("Пароль Kris (на экране не виден): ").encode()).hexdigest()
    start = (date.today() - timedelta(days=6)).isoformat()
    end = (date.today() + timedelta(days=1)).isoformat()
    print("Период для проверки: последние 7 дней\n")
    for base in HOSTS:
        key = None
        try:
            key = get(base + "/auth?" + urllib.parse.urlencode({"login": LOGIN, "pass": h})).strip()
            cols = json.loads(get(base + "/v2/reports/olap/columns?reportType=SALES&key=" + key))
            fields = [f for f, v in cols.items() if any(k in f.lower() for k in KEYS) and not f.endswith((".Id", ".ID", ".Ids", ".IDs", ".GUID"))
                      and (v.get("groupingAllowed", True) if isinstance(v, dict) else True)]
            print("=== " + base.split("//")[1].split("/")[0])
            print("Подходящих полей:", len(fields))
            for f in fields:
                v = cols[f]
                label = v.get("name") if isinstance(v, dict) else ""
                try:
                    body = json.dumps({"reportType": "SALES", "buildSummary": "false",
                                       "groupByRowFields": [f],
                                       "aggregateFields": ["DishDiscountSumInt", "UniqOrderId.OrdersCount"],
                                       "filters": {"OpenDate.Typed": {"filterType": "DateRange", "periodType": "CUSTOM",
                                                                      "from": start, "to": end,
                                                                      "includeLow": "true", "includeHigh": "false"}}}).encode()
                    rows = json.loads(get(base + "/v2/reports/olap?key=" + key, body)).get("data", [])
                    rows = [r for r in rows if r.get("UniqOrderId.OrdersCount")]
                    rows.sort(key=lambda r: -(r.get("DishDiscountSumInt") or 0))
                    print("\n%s (%s): значений %d" % (f, label, len(rows)))
                    for r in rows[:6]:
                        o = r["UniqOrderId.OrdersCount"]
                        t = r.get("DishDiscountSumInt") or 0
                        print("   %-30s чеков %5d  выручка %8d  ср.чек %6d" % (str(r.get(f))[:30], o, t, t / o))
                except Exception as e:
                    print("\n%s (%s): не удалось (%s)" % (f, label, str(e)[:80]))
        except Exception as e:
            print(base, "- ошибка:", e)
        finally:
            if key:
                try:
                    get(base + "/logout?key=" + key)
                except Exception:
                    pass
            print()
    print("Готово, из iiko вышли.")


main()
