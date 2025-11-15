import os
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask

# ============================
#   إعدادات أساسية
# ============================

BOT_TOKEN = os.getenv("BOT_TOKEN", "8278742496:AAH8lDMB0ci6mX0I7JIiIbuB8ZudyWVqT3E")
CHAT_ID = os.getenv("CHAT_ID", "@F90Sports")

# المفتاح الرئيسي من API-FOOTBALL
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "f75265ca25cdfb56f0907dfff86d1226")

if not BOT_TOKEN or not API_FOOTBALL_KEY:
    print("❌ BOT_TOKEN أو API_FOOTBALL_KEY غير مضبوطين في Environment Variables!")

# توقيت القدس (تقريبي UTC+2)
TZ_OFFSET = 2

# إعدادات التكرار
LIVE_POLL_SECONDS = 60            # فحص المباريات الجارية كل 60 ثانية
SCHEDULE_EVERY_SECONDS = 1800     # نشر جدول المباريات كل 30 دقيقة
TOPSCORERS_EVERY_SECONDS = 12 * 3600   # الهدافين كل 12 ساعة
MATCH_OF_WEEK_EVERY_SECONDS = 12 * 3600  # مباراة الأسبوع كل 12 ساعة
DAILY_SUMMARY_SECONDS = 3600      # فحص ملخص اليوم كل ساعة

# دوريات مهمة
IMPORTANT_LEAGUES = [
    39,   # Premier League
    140,  # La Liga
    135,  # Serie A
    78,   # Bundesliga
    61,   # Ligue 1
    2,    # Champions League
    3,    # Europa League
    848,  # Saudi Pro League
]

# فرق VIP برسائل مميزة
FAVORITE_TEAMS = [
    "Real Madrid",
    "Barcelona",
    "Al Nassr",
    "Al Ittihad",
]

# فوتر ثابت لكل الرسائل
FOOTER = (
    "\n\n————————————\n"
    "📢 تابعوا أحدث الأخبار الرياضية لحظة بلحظة على قناة F90 Sports:\n"
    "📡 @F90Sports\n"
    "📰 ولأخبار العالم وفلسطين أولاً بأول تابعوا: @f90newsnow\n"
    "📺 البث المباشر وروابط المشاهدة تُضاف من الإدارة عند التوفر."
)

# ============================
#   أدوات عامة
# ============================

def tg_send_message(text: str):
    """إرسال نص لتلجرام مع فوتر."""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN مفقود.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text + FOOTER,
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, data=payload, timeout=20)
        if r.status_code != 200:
            print("Telegram sendMessage error:", r.text)
    except Exception as e:
        print("Telegram sendMessage exception:", e)


def tg_send_photo(photo_url: str, caption: str):
    """إرسال صورة + كابشن (مع فوتر). لو فشل، يرسل نص فقط."""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN مفقود.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {
        "chat_id": CHAT_ID,
        "caption": caption + FOOTER,
        "parse_mode": "HTML",
        "photo": photo_url,
    }
    try:
        r = requests.post(url, data=data, timeout=20)
        if r.status_code != 200:
            print("Telegram sendPhoto error:", r.text)
            tg_send_message(caption)
    except Exception as e:
        print("Telegram sendPhoto exception:", e)
        tg_send_message(caption)


def api_football_get(path: str, params: dict | None = None) -> dict:
    """استدعاء API-FOOTBALL."""
    if not API_FOOTBALL_KEY:
        print("❌ API_FOOTBALL_KEY مفقود.")
        return {"response": []}

    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    base = "https://v3.football.api-sports.io"
    try:
        r = requests.get(base + path, headers=headers, params=params, timeout=25)
        data = r.json()
        if data.get("errors"):
            print("API-FOOTBALL errors:", data["errors"])
        return data
    except Exception as e:
        print("API-FOOTBALL exception:", e)
        return {"response": []}


def utc_to_local_str(iso_str: str) -> str:
    """تحويل وقت ISO إلى نص بالعربية بتوقيت القدس تقريبياً."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
        dt_local = dt + timedelta(hours=TZ_OFFSET)
        return dt_local.strftime("%Y-%m-%d • %H:%M")
    except Exception:
        return iso_str


def is_favorite_match(fixture: dict) -> bool:
    """هل المباراة تخص فريق VIP؟"""
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    for name in FAVORITE_TEAMS:
        if name.lower() in home.lower() or name.lower() in away.lower():
            return True
    return False


# ============================
#   جدول المباريات
# ============================

def fetch_fixtures_for_dates(date_from: str, date_to: str) -> list:
    fixtures: list = []

    for league_id in IMPORTANT_LEAGUES:
        params = {
            "from": date_from,
            "to": date_to,
            "league": league_id,
            "season": datetime.utcnow().year,
            "timezone": "UTC",
        }
        data = api_football_get("/fixtures", params=params)
        fixtures.extend(data.get("response", []))

    return fixtures


def group_text(title: str, fixtures: list) -> str:
    if not fixtures:
        return f"📆 <b>{title}</b>\nلا توجد مباريات مسجّلة.\n"
    lines = [f"📆 <b>{title}</b>"]
    fixtures_sorted = sorted(fixtures, key=lambda x: x["fixture"]["date"])
    for fx in fixtures_sorted[:60]:
        f = fx["fixture"]
        l = fx["league"]
        t = fx["teams"]
        time_str = utc_to_local_str(f["date"])
        home = t["home"]["name"]
        away = t["away"]["name"]
        league_name = l["name"]
        lines.append(
            f"🏟 {home} vs {away}\n"
            f"   🏆 {league_name}\n"
            f"   ⏰ {time_str}"
        )
    return "\n".join(lines)


def build_schedule_message() -> tuple[str, list]:
    now = datetime.utcnow()
    today = now.date()
    tomorrow = today + timedelta(days=1)
    week_later = today + timedelta(days=7)

    fixtures_today = fetch_fixtures_for_dates(str(today), str(today))
    fixtures_tomorrow = fetch_fixtures_for_dates(str(tomorrow), str(tomorrow))
    fixtures_week = fetch_fixtures_for_dates(str(today + timedelta(days=2)), str(week_later))

    msg_parts = [
        "🏟️ <b>جدول المباريات (اليوم • غداً • هذا الأسبوع)</b>\n",
        group_text("مباريات اليوم", fixtures_today),
        "",
        group_text("مباريات الغد", fixtures_tomorrow),
        "",
        group_text("هذا الأسبوع (أهم المباريات)", fixtures_week),
    ]
    return "\n".join(msg_parts), fixtures_today


def send_schedule_text_and_vip_posters():
    """يرسل الجدول + بوسترات خاصة للمباريات الكبيرة وVIP."""
    schedule_msg, fixtures_today = build_schedule_message()
    tg_send_message(schedule_msg)

    # بوسترات للمباريات اليوم فقط (خاصة لـ VIP)
    for fx in fixtures_today:
        if not is_favorite_match(fx):
            continue

        f = fx["fixture"]
        l = fx["league"]
        t = fx["teams"]

        home = t["home"]["name"]
        away = t["away"]["name"]
        league_name = l["name"]
        time_str = utc_to_local_str(f["date"])
        status = f["status"]["long"]

        caption = (
            "🔥 <b>مباراة مميزة لعشاق F90 Sports</b>\n\n"
            f"🏟 {home} vs {away}\n"
            f"🏆 {league_name}\n"
            f"⏰ {time_str}\n"
            f"📡 الحالة الحالية: {status}\n\n"
            "📺 البث: سيتم إضافة الرابط من قبل الإدارة عند التوفر.\n"
            "📣 قناة الرياضة: @F90Sports"
        )

        # نحاول استخدام لوجو الهوم أو الضيف
        logo = t["home"].get("logo") or t["away"].get("logo")
        if logo:
            tg_send_photo(logo, caption)
        else:
            tg_send_message(caption)


# ============================
#   هدافي الدوريات (Top Scorers)
# ============================

def send_top_scorers():
    """نشر هدافي أهم الدوريات."""
    msg_parts = ["⚽️ <b>قوائم هدافي الدوريات (إحصائيات تقريبية)</b>\n"]

    for league_id in IMPORTANT_LEAGUES[:5]:  # نكتفي بـ 5 دوريات
        data = api_football_get("/players/topscorers", params={
            "league": league_id,
            "season": datetime.utcnow().year,
        })
        resp = data.get("response", [])
        if not resp:
            continue

        league_name = resp[0]["statistics"][0]["league"]["name"]
        msg_parts.append(f"🏆 <b>{league_name}</b>:")

        for i, p in enumerate(resp[:5], start=1):
            player_name = p["player"]["name"]
            team_name = p["statistics"][0]["team"]["name"]
            goals = p["statistics"][0]["goals"]["total"]
            msg_parts.append(f"{i}. {player_name} ({team_name}) – {goals} هدف")

        msg_parts.append("")

    if len(msg_parts) > 1:
        tg_send_message("\n".join(msg_parts))


# ============================
#   مباراة الأسبوع + توقع بسيط
# ============================

def pick_match_of_week():
    """اختيار مباراة قوية من هذا الأسبوع."""
    today = datetime.utcnow().date()
    week_later = today + timedelta(days=7)
    fixtures_week = fetch_fixtures_for_dates(str(today), str(week_later))

    if not fixtures_week:
        return None

    # نختار مباراة فيها فريق VIP أولاً
    vip_matches = [f for f in fixtures_week if is_favorite_match(f)]
    if vip_matches:
        return vip_matches[0]

    # وإلا نختار مباراة من دوري قوي (Champions League مثلاً)
    for fx in fixtures_week:
        league_name = fx["league"]["name"].lower()
        if "champions" in league_name:
            return fx

    # أخيراً، أول مباراة في اللائحة
    return fixtures_week[0]


def simple_predict(home_name: str, away_name: str) -> str:
    """توقع بسيط (ليس ذكاء حقيقي، فقط شكل)."""
    big = ["real madrid", "barcelona", "manchester city", "bayern", "liverpool", "al nassr", "al ittihad"]
    score = 0
    if any(b in home_name.lower() for b in big):
        score += 1
    if any(b in away_name.lower() for b in big):
        score -= 1

    if score > 0:
        return f"🧠 التوقع: فوز {home_name} أو تعادل."
    elif score < 0:
        return f"🧠 التوقع: فوز {away_name} أو تعادل."
    else:
        return "🧠 التوقع: مباراة متقاربة جداً، فرص متساوية."


def send_match_of_week():
    fx = pick_match_of_week()
    if not fx:
        print("لا يوجد مباراة أسبوع مناسبة.")
        return

    f = fx["fixture"]
    l = fx["league"]
    t = fx["teams"]

    home = t["home"]["name"]
    away = t["away"]["name"]
    league_name = l["name"]
    time_str = utc_to_local_str(f["date"])

    txt = (
        "💥 <b>مباراة الأسبوع – F90 Sports</b>\n\n"
        f"🏟 {home} vs {away}\n"
        f"🏆 {league_name}\n"
        f"⏰ {time_str}\n\n"
        f"{simple_predict(home, away)}\n\n"
        "📺 البث والقنوات الناقلة يتم إضافتها من الإدارة عند التوفر."
    )

    logo = t["home"].get("logo") or t["away"].get("logo")
    if logo:
        tg_send_photo(logo, txt)
    else:
        tg_send_message(txt)


# ============================
#   لايف: أهداف + كروت + تبديلات
# ============================

live_state: dict[int, dict] = {}     # fixture_id -> {score_home, score_away, status}
seen_events: set[str] = set()
pre_alerts: dict[int, dict] = {}     # fixture_id -> {"10":bool, "5":bool}


def fetch_live_fixtures():
    data = api_football_get("/fixtures", params={"live": "all", "timezone": "UTC"})
    return data.get("response", [])


def fetch_fixture_events(fixture_id: int):
    data = api_football_get("/fixtures/events", params={"fixture": fixture_id})
    return data.get("response", [])


def fetch_fixture_stats(fixture_id: int):
    data = api_football_get("/fixtures/statistics", params={"fixture": fixture_id})
    return data.get("response", [])


def ensure_pre_alerts(fixture_id: int):
    if fixture_id not in pre_alerts:
        pre_alerts[fixture_id] = {"10": False, "5": False}


def check_and_send_pre_match_alerts(fx: dict):
    """تنبيه قبل 10 دقائق و5 دقائق من البداية."""
    f = fx["fixture"]
    fixture_id = f["id"]
    date_iso = f.get("date")
    if not date_iso:
        return
    try:
        dt_utc = datetime.fromisoformat(date_iso.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
    except Exception:
        return

    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    minutes_to_ko = (dt_utc - now_utc).total_seconds() / 60.0

    ensure_pre_alerts(fixture_id)

    home = fx["teams"]["home"]["name"]
    away = fx["teams"]["away"]["name"]
    league_name = fx["league"]["name"]
    time_str = utc_to_local_str(date_iso)

    base_txt = (
        f"🏟 {home} vs {away}\n"
        f"🏆 {league_name}\n"
        f"⏰ {time_str}"
    )

    # قبل 10 دقائق
    if 5 < minutes_to_ko <= 10 and not pre_alerts[fixture_id]["10"]:
        tg_send_message("⏳ <b>بعد 10 دقائق تنطلق مباراة:</b>\n" + base_txt)
        pre_alerts[fixture_id]["10"] = True

    # قبل 5 دقائق
    if 0 < minutes_to_ko <= 5 and not pre_alerts[fixture_id]["5"]:
        tg_send_message("⏳ <b>بعد 5 دقائق تنطلق مباراة:</b>\n" + base_txt)
        pre_alerts[fixture_id]["5"] = True


def format_live_header(fx: dict) -> str:
    f = fx["fixture"]
    l = fx["league"]
    t = fx["teams"]
    goals = fx["goals"]

    home = t["home"]["name"]
    away = t["away"]["name"]
    league_name = l["name"]
    status = f["status"]["long"]
    elapsed = f["status"]["elapsed"]
    score = f"{goals['home']} - {goals['away']}"
    minute_part = f" {elapsed}'" if elapsed is not None else ""

    return (
        f"🏟 {home} vs {away}\n"
        f"🏆 {league_name}\n"
        f"⏱ {status}{minute_part}\n"
        f"🔢 النتيجة: {score}"
    )


def format_half_stats(stats_resp: list) -> str:
    if not stats_resp:
        return "📊 لا توجد إحصائيات متاحة حالياً."
    lines = ["📊 <b>إحصائيات المباراة (تقريبية)</b>"]
    for team_stats in stats_resp:
        team_name = team_stats["team"]["name"]
        lines.append(f"\n🔹 {team_name}:")
        for s in team_stats["statistics"]:
            t = s["type"]
            v = s["value"]
            if v is None:
                continue
            if t in ["Shots on Goal", "Shots off Goal", "Total Shots", "Ball Possession", "Yellow Cards", "Red Cards"]:
                lines.append(f"- {t}: {v}")
    return "\n".join(lines)


def send_final_match_summary(fx: dict):
    """رسالة خاصة بعد نهاية كل مباراة."""
    f = fx["fixture"]
    t = fx["teams"]
    l = fx["league"]
    goals = fx["goals"]

    home = t["home"]["name"]
    away = t["away"]["name"]
    league_name = l["name"]
    score = f"{goals['home']} - {goals['away']}"
    time_str = utc_to_local_str(f["date"])

    txt = (
        "🏁 <b>نهاية المباراة</b>\n\n"
        f"🏟 {home} vs {away}\n"
        f"🏆 {league_name}\n"
        f"⏰ توقيت البداية: {time_str}\n"
        f"🔢 النتيجة النهائية: {score}\n\n"
        "📊 للمزيد من التفاصيل والإحصائيات تابعوا الرسائل التالية عند التوفر."
    )
    tg_send_message(txt)


def process_live_fixtures():
    global live_state

    live = fetch_live_fixtures()
    if not live:
        print("لا توجد مباريات جارية الآن.")
        return

    for fx in live:
        f = fx["fixture"]
        fixture_id = f["id"]

        # تنبيهات قبل المباراة
        check_and_send_pre_match_alerts(fx)

        prev = live_state.get(fixture_id)
        goals = fx["goals"]
        score_home = goals["home"]
        score_away = goals["away"]
        status_short = f["status"]["short"]  # "1H", "HT", "2H", "FT"...

        # أول مرة نرى المباراة لايف
        if not prev:
            header = format_live_header(fx)
            if is_favorite_match(fx):
                tg_send_message("🎬 <b>انطلاق مباراة مهمة لفِرقك المفضلة!</b>\n" + header)
            else:
                tg_send_message("🎬 <b>انطلاق مباراة</b>\n" + header)

            live_state[fixture_id] = {
                "score_home": score_home,
                "score_away": score_away,
                "status": status_short,
                "ht_stats_sent": False,
            }
        else:
            # تغيير في النتيجة (هدف)
            if score_home != prev["score_home"] or score_away != prev["score_away"]:
                header = format_live_header(fx)
                if is_favorite_match(fx):
                    tg_send_message("⚽️ <b>هدف في مباراة فريقك المفضل!</b>\n" + header)
                else:
                    tg_send_message("⚽️ <b>هدف جديد!</b>\n" + header)

                prev["score_home"] = score_home
                prev["score_away"] = score_away

            # تغيير حالة المباراة (HT, FT, إلخ)
            if status_short != prev["status"]:
                header = format_live_header(fx)
                if status_short == "HT":
                    tg_send_message("⏸ <b>نهاية الشوط الأول</b>\n" + header)
                    try:
                        stats = fetch_fixture_stats(fixture_id)
                        stats_txt = format_half_stats(stats)
                        tg_send_message(stats_txt)
                    except Exception as e:
                        print("Stats error:", e)
                    prev["ht_stats_sent"] = True
                elif status_short == "FT":
                    tg_send_message("🏁 <b>نهاية المباراة</b>\n" + header)
                    send_final_match_summary(fx)
                else:
                    tg_send_message("🔄 <b>تحديث حالة المباراة</b>\n" + header)

                prev["status"] = status_short

        # أحداث التفاصيل: أهداف، بطاقات، تبديلات
        events = fetch_fixture_events(fixture_id)
        for ev in events:
            key = (
                f"{fixture_id}-"
                f"{ev.get('time', {}).get('elapsed')}-"
                f"{ev.get('team', {}).get('id')}-"
                f"{ev.get('player', {}).get('id')}-"
                f"{ev.get('type')}-"
                f"{ev.get('detail')}"
            )
            if key in seen_events:
                continue
            seen_events.add(key)

            ev_type = ev.get("type")
            detail = ev.get("detail", "")
            minute = ev.get("time", {}).get("elapsed")
            team_name = ev.get("team", {}).get("name", "")
            player = ev.get("player", {}).get("name", "")
            assist = ev.get("assist", {}).get("name", "")

            base = f"⏱ {minute}' • {team_name}\n👤 {player}"
            if assist:
                base += f" (🎯 تمريرة: {assist})"

            if ev_type == "Goal":
                msg = f"⚽️ <b>هدف!</b>\n{base}"
                tg_send_message(msg)
            elif ev_type == "Card":
                if "Yellow" in detail:
                    msg = f"🟨 <b>بطاقة صفراء</b>\n{base}"
                elif "Red" in detail:
                    msg = f"🟥 <b>بطاقة حمراء</b>\n{base}"
                else:
                    msg = f"🟧 <b>بطاقة</b>\n{base} • {detail}"
                tg_send_message(msg)
            elif ev_type == "subst":
                msg = f"🔁 <b>تبديل</b>\n{base}"
                tg_send_message(msg)


# ============================
#   ملخص نهاية اليوم + ترتيب
# ============================

last_summary_date: str | None = None

def fetch_standings(league_id: int) -> list:
    data = api_football_get("/standings", params={
        "league": league_id,
        "season": datetime.utcnow().year,
    })
    resp = data.get("response", [])
    if not resp:
        return []
    # الشكل: response[0]["league"]["standings"][0] قائمة فرق
    try:
        return resp[0]["league"]["standings"][0]
    except Exception:
        return []


def send_daily_summary_if_needed():
    global last_summary_date
    today = datetime.utcnow().date().isoformat()
    if last_summary_date == today:
        return

    # نجلب مباريات اليوم المنتهية فقط
    fixtures_today = fetch_fixtures_for_dates(today, today)
    finished = [f for f in fixtures_today if f["fixture"]["status"]["short"] == "FT"]

    if not finished:
        print("لا توجد مباريات منتهية اليوم لملخص اليوم.")
        return

    lines = ["📊 <b>ملخص مباريات اليوم – F90 Sports</b>\n"]
    for fx in sorted(finished, key=lambda x: x["fixture"]["date"]):
        f = fx["fixture"]
        t = fx["teams"]
        l = fx["league"]
        g = fx["goals"]
        home = t["home"]["name"]
        away = t["away"]["name"]
        league_name = l["name"]
        score = f"{g['home']} - {g['away']}"
        lines.append(
            f"🏟 {home} vs {away}\n"
            f"   🏆 {league_name}\n"
            f"   🔢 النتيجة: {score}\n"
        )

    tg_send_message("\n".join(lines))

    # ترتيب مختصر لعدة دوريات
    table_lines = ["📈 <b>ترتيب مختصر لأهم الدوريات</b>\n"]
    for league_id in IMPORTANT_LEAGUES[:5]:
        st = fetch_standings(league_id)
        if not st:
            continue
        league_name = st[0]["league"]["name"] if "league" in st[0] else ""
        if not league_name:
            # نحاول من API مرة أخرى
            pass
        table_lines.append(f"🏆 <b>{st[0]['league']['name'] if 'league' in st[0] else 'دوري'}</b>:")
        for row in st[:5]:
            team_name = row["team"]["name"]
            pts = row["points"]
            played = row["all"]["played"]
            table_lines.append(f"- {team_name}: {pts} نقطة من {played} مباراة")
        table_lines.append("")

    if len(table_lines) > 1:
        tg_send_message("\n".join(table_lines))

    last_summary_date = today
    print("✅ تم إرسال ملخص اليوم + ترتيب مختصر.")


# ============================
#   حلقة التشغيل الرئيسية
# ============================

def run_loop():
    print("🚀 F90 Sports Live Bot started...")
    last_schedule = 0
    last_topscorers = 0
    last_match_of_week = 0
    last_daily_summary_check = 0

    while True:
        now = time.time()

        # 1) جدول المباريات + بوسترات VIP كل 30 دقيقة
        if now - last_schedule > SCHEDULE_EVERY_SECONDS:
            try:
                send_schedule_text_and_vip_posters()
            except Exception as e:
                print("Schedule error:", e)
            last_schedule = now

        # 2) هدافي الدوريات كل 12 ساعة
        if now - last_topscorers > TOPSCORERS_EVERY_SECONDS:
            try:
                send_top_scorers()
            except Exception as e:
                print("Topscorers error:", e)
            last_topscorers = now

        # 3) مباراة الأسبوع كل 12 ساعة
        if now - last_match_of_week > MATCH_OF_WEEK_EVERY_SECONDS:
            try:
                send_match_of_week()
            except Exception as e:
                print("Match-of-week error:", e)
            last_match_of_week = now

        # 4) ملخص نهاية اليوم + الترتيب (نفحص كل ساعة)
        if now - last_daily_summary_check > DAILY_SUMMARY_SECONDS:
            try:
                send_daily_summary_if_needed()
            except Exception as e:
                print("Daily summary error:", e)
            last_daily_summary_check = now

        # 5) بث لايف دائم
        try:
            process_live_fixtures()
        except Exception as e:
            print("Live processing error:", e)

        time.sleep(LIVE_POLL_SECONDS)


# ============================
#   Flask لرندر
# ============================

app = Flask(__name__)

@app.route("/")
def home():
    return "✅ F90 Sports Live Bot is running."

@app.route("/test")
def test():
    tg_send_message("✅ اختبار من بوت F90 Sports – إذا وصلتك هذه الرسالة فالبوت شغال.")
    return "Test message sent."


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    import threading
    threading.Thread(target=run_flask, daemon=True).start()
    run_loop()
