# Погода для Пензы (Open-Meteo, бесплатно, без ключа) и грубая поправка к прогнозу выручки.
# Поправка осторожная: по продажам за ~2 месяца дождливые и холодные дни дали выручку на 10-15% ниже обычной,
# но таких дней мало, поэтому берём примерно половину замеченного эффекта.
import json, urllib.request

LAT, LON = 53.2, 45.0
RAIN_MM = 1.0       # столько осадков за оставшиеся часы считаем «будет дождь»
COLD_C = 8.0        # холоднее считаем «холодно»
RAIN_FACTOR, COLD_FACTOR, FLOOR = 0.93, 0.95, 0.88


def today_weather(now, until=21):
    """Погода на оставшуюся часть дня. None, если источник недоступен."""
    try:
        url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&hourly=temperature_2m,precipitation"
               "&timezone=Europe%%2FMoscow&forecast_days=1" % (LAT, LON))
        with urllib.request.urlopen(url, timeout=15) as r:
            h = json.loads(r.read().decode())["hourly"]
    except Exception:
        return None
    left = [(int(t[11:13]), te, p or 0) for t, te, p in zip(h["time"], h["temperature_2m"], h["precipitation"])
            if t[:10] == now.date().isoformat() and now.hour <= int(t[11:13]) < until]
    if not left:
        return None
    rain = sum(p for _, _, p in left)
    temp = sum(te for _, te, _ in left) / len(left)
    factor = 1.0
    notes = []
    if rain >= RAIN_MM:
        factor *= RAIN_FACTOR
        wet = [hr for hr, _, p in left if p >= 0.2]
        notes.append("дождь %02d:00–%02d:00 (около %.1f мм)" % (wet[0], wet[-1] + 1, rain) if wet else "осадки (около %.1f мм)" % rain)
    if temp < COLD_C:
        factor *= COLD_FACTOR
        notes.append("холодно")
    factor = max(factor, FLOOR)
    line = "🌦 Погода до вечера: %d°C%s" % (round(temp), ", " + ", ".join(notes) if notes else ", без осадков")
    return {"factor": factor, "line": line, "rain": rain, "temp": temp}


COOL_C, HOT_C = 14.0, 24.0   # ниже: прохладно, нужны горячие напитки; выше: жарко, нужны холодные


def drink_tip(wx):
    """Короткий непринуждённый совет по напиткам в зависимости от температуры, или None, если погода обычная."""
    if not wx:
        return None
    t = round(wx["temp"])
    if wx["temp"] < COOL_C:
        word = "холодно" if wx["temp"] < 8 else "прохладно"
        return "Сегодня %s (%d°C): делайте акцент на горячих напитках, чай, какао, кофе, и к ним выпечка или десерт." % (word, t)
    if wx["temp"] >= HOT_C:
        return "Сегодня жарко (%d°C): предлагайте гостям прохладительные напитки." % t
    return None
