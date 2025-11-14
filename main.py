import os
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask

# ============================
#   قراءه المفاتيح من Render
# ============================

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
CHAT_ID = os.getenv("CHAT_ID", "@F90Sports")

if not BOT_TOKEN or not API_FOOTBALL_KEY:
    print("❌ ERROR: BOT_TOKEN أو API_FOOTBALL_KEY غير مضبوطين في Environment Variables!")
    exit()

# ============================
#   إعدادات ثابتة
# ============================

TZ_OFFSET = 2
LIVE_POLL_SECONDS = 60
SCHEDULE_EVERY_SECONDS = 1800
TOPSCORERS_EVERY_SECONDS = 43200
MATCH_OF_WEEK_EVERY_SECONDS = 43200

IMPORTANT_LEAGUES = [39, 140, 135, 78, 61, 2, 3, 848]

FAVORITE_TEAMS = ["Real Madrid", "Barcelona", "Al Nassr", "Al Ittihad"]

# ============================
#   أدوات تلجرام
# ============================

def tg_send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except:
        pass


def tg_send_photo(photo_url, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        r = requests.post(
            url,
            data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
            files={"photo": requests.get(photo_url, timeout=10).content},
            timeout=15
        )
        if r.status_code != 200:
            tg_send_message(caption)
    except:
        tg_send_message(caption)

# ============================
#   API-Football
# ============================

def api_football_get(path, params=None):
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    try:
        r = requests.get("https://v3.football.api-sports.io" + path, headers=headers, params=params, timeout=15)
        data = r.json()
        return data
    except:
        return {"response": []}

# ============================

def utc_to_local(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
        return (dt + timedelta(hours=TZ_OFFSET)).strftime("%Y-%m-%d • %H:%M")
    except:
        return iso

# ============================
#   جلب مباريات حسب التاريخ
# ============================

def fetch_fixtures(start_date, end_date):
    all_fx = []
    for lg in IMPORTANT_LEAGUES:
        data = api_football_get("/fixtures", {
            "from": start_date,
            "to": end_date,
            "season": datetime.utcnow().year,
            "league": lg
        })
        all_fx.extend(data.get("response", []))
    return all_fx

# ============================
#   جداول
# ============================

def format_group(title, matches):
    if not matches:
        return f"📆 <b>{title}</b>\nلا توجد مباريات مسجّلة.\n"

    text = f"📆 <b>{title}</b>\n"
    matches = sorted(matches, key=lambda m: m["fixture"]["date"])

    for fx in matches:
        f = fx["fixture"]
        t = fx["teams"]
        l = fx["league"]
        time_txt = utc_to_local(f["date"])
        text += (
            f"\n🏟 {t['home']['name']} vs {t['away']['name']}"
            f"\n🏆 {l['name']}"
            f"\n⏰ {time_txt}\n"
        )
    return text

def send_daily_schedule():
    today = datetime.utcnow().date()
    tomorrow = today + timedelta(days=1)
    week = today + timedelta(days=7)

    fx_today = fetch_fixtures(str(today), str(today))
    fx_tomorrow = fetch_fixtures(str(tomorrow), str(tomorrow))
    fx_week = fetch_fixtures(str(today + timedelta(days=2)), str(week))

    msg = (
        "🏟️ <b>جدول المباريات (اليوم • غداً • الأسبوع)</b>\n\n"
        + format_group("مباريات اليوم", fx_today) + "\n"
        + format_group("مباريات الغد", fx_tomorrow) + "\n"
        + format_group("هذا الأسبوع", fx_week) + "\n"
        "————————————\n"
        "📡 القنوات الناقلة يتم إضافتها من الإدارة عند التوفّر.\n"
        "📺 قناة الرياضة: @F90Sports\n"
        "📰 قناة الأخبار: @f90newsnow"
    )

    tg_send_message(msg)

# ============================
#   لايف
# ============================

live_state = {}
seen_events = set()

def fetch_live():
    return api_football_get("/fixtures", {"live": "all"}).get("response", [])

def fetch_events(fid):
    return api_football_get("/fixtures/events", {"fixture": fid}).get("response", [])

def live_loop():
    live = fetch_live()

    for fx in live:
        fid = fx["fixture"]["id"]
        f = fx["fixture"]
        t = fx["teams"]
        goals = fx["goals"]

        # أول دخول
        if fid not in live_state:
            live_state[fid] = {
                "home": goals["home"],
                "away": goals["away"],
            }

            tg_send_message(
                f"🎬 <b>انطلاق مباراة</b>\n"
                f"🏟 {t['home']['name']} vs {t['away']['name']}\n"
                f"⏱ {f['status']['long']}"
            )

        # فحص أهداف
        prev = live_state[fid]

        if goals["home"] != prev["home"] or goals["away"] != prev["away"]:
            prev["home"] = goals["home"]
            prev["away"] = goals["away"]

            tg_send_message(
                f"⚽️ <b>هدف!</b>\n"
                f"{t['home']['name']} {goals['home']} - {goals['away']} {t['away']['name']}"
            )

        # فحص أحداث
        events = fetch_events(fid)
        for ev in events:
            key = str(ev)
            if key in seen_events:
                continue
            seen_events.add(key)

            minute = ev["time"]["elapsed"]
            team = ev["team"]["name"]
            player = ev["player"]["name"]
            detail = ev["detail"]
            type_ev = ev["type"]

            if type_ev == "Goal":
                tg_send_message(f"⚽️ هدف {team}\n⏱ {minute}'\n👤 {player}")
            elif type_ev == "Card":
                ic = "🟥" if "Red" in detail else "🟨"
                tg_send_message(f"{ic} بطاقة لـ {team}\n⏱ {minute}'\n👤 {player}")
            elif type_ev == "subst":
                tg_send_message(f"🔁 تبديل {team}\n⏱ {minute}'\n👤 {player}")

# ============================
#   LOOP رئيسي
# ============================

def run_loop():
    print("🔥 Bot Started")

    last_schedule = 0

    while True:
        now = time.time()

        # جدول المباريات كل 30 دقيقة
        if now - last_schedule > SCHEDULE_EVERY_SECONDS:
            send_daily_schedule()
            last_schedule = now

        # بث مباشر
        live_loop()

        time.sleep(LIVE_POLL_SECONDS)

# ============================
#   Flask + Render
# ============================

app = Flask(__name__)

@app.route("/")
def home():
    return "F90 SPORTS BOT IS RUNNING ✔️"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ============================

if __name__ == "__main__":
    import threading
    threading.Thread(target=run_flask, daemon=True).start()
    run_loop()
