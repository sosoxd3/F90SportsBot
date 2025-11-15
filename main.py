import os
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask

# ============================
#   إعدادات أساسية (Env Vars)
# ============================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID", "@F90Sports")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")

if not BOT_TOKEN or not API_FOOTBALL_KEY:
    print("❌ BOT_TOKEN أو API_FOOTBALL_KEY غير مضبوطين في Environment Variables!")

# توقيت القدس (تقريبي UTC+2)
TZ_OFFSET = 2

# إعدادات تكرار
LIVE_POLL_SECONDS = 60             # فحص لايف كل 60 ثانية
SCHEDULE_EVERY_SECONDS = 1800      # نشر جدول كل 30 دقيقة
TOPSCORERS_EVERY_SECONDS = 12 * 3600
MATCH_OF_WEEK_EVERY_SECONDS = 12 * 3600
FAVORITES_EVERY_SECONDS = 1800     # جدول خاص للفرق الكبيرة كل 30 دقيقة

# دوريات مهمة (IDs من API-FOOTBALL)
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

# فرق VIP – جدول خاص وتنبيهات خاصة
FAVORITE_TEAMS = [
    "Real Madrid",
    "Barcelona",
    "Manchester City",
    "Liverpool",
    "Chelsea",
    "Bayern Munich",
    "Paris Saint Germain",
    "Al Nassr",
    "Al Hilal",
    "Al Ittihad",
]

# ============================
#   أدوات عامة
# ============================

def tg_send_message(text: str):
    """إرسال نص لتلجرام."""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN مفقود.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        if r.status_code != 200:
            print("Telegram sendMessage error:", r.text)
    except Exception as e:
        print("Telegram sendMessage exception:", e)


def tg_send_photo(photo_url: str, caption: str):
    """إرسال صورة + كابشن. لو فشل يرسل نص فقط."""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN مفقود.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        r = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "caption": caption,
                "parse_mode": "HTML",
                "photo": photo_url,
            },
            timeout=20,
        )
        if r.status_code != 200:
            print("Telegram sendPhoto error:", r.text)
            tg_send_message(caption)
    except Exception as e:
        print("Telegram sendPhoto exception:", e)
        tg_send_message(caption)


def api_football_get(path: str, params: dict | None = None) -> dict:
    """استدعاء API-FOOTBALL."""
    headers = {"x-apisports-key": API_FOOTBALL_KEY} if API_FOOTBALL_KEY else {}
    base = "https://v3.football.api-sports.io"
    try:
        r = requests.get(base + path, headers=headers, params=params, timeout=20)
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
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).replace(
            tzinfo=timezone.utc
        )
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
#   جلب المباريات القادمة (Next)
# ============================

def fetch_next_fixtures(limit: int = 50) -> list[dict]:
    """
    جلب أول (limit) مباراة قادمة من كل العالم.
    هذا يضمن دائماً وجود جدول حتى لو بعد شهر أو سنة.
    """
    data = api_football_get("/fixtures", params={"next": limit, "timezone": "UTC"})
    return data.get("response", [])


def group_schedule_text(fixtures: list[dict]) -> str:
    """
    تنسيق جدول عام:
    - مباريات اليوم
    - مباريات الغد
    - مباريات أخرى قادمة
    """

    today = datetime.utcnow().date()
    tomorrow = today + timedelta(days=1)

    today_matches = []
    tomorrow_matches = []
    later_matches = []

    for fx in fixtures:
        date_iso = fx["fixture"]["date"]
        try:
            dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
            d = dt.date()
        except Exception:
            d = today

        if d == today:
            today_matches.append(fx)
        elif d == tomorrow:
            tomorrow_matches.append(fx)
        else:
            later_matches.append(fx)

    parts: list[str] = []
    parts.append("🏟️ <b>جدول المباريات القادمة (F90 Sports)</b>\n")

    def block(title: str, items: list[dict]) -> str:
        if not items:
            return f"📆 <b>{title}</b>\nلا توجد مباريات.\n"
        lines = [f"📆 <b>{title}</b>"]
        for fx in items[:40]:
            f = fx["fixture"]
            l = fx["league"]
            t = fx["teams"]

            home = t["home"]["name"]
            away = t["away"]["name"]
            league_name = l["name"]
            time_str = utc_to_local_str(f["date"])

            lines.append(
                f"🏟 {home} vs {away}\n"
                f"   🏆 {league_name}\n"
                f"   ⏰ {time_str}"
            )
        return "\n".join(lines)

    parts.append(block("مباريات اليوم", today_matches))
    parts.append("")
    parts.append(block("مباريات الغد", tomorrow_matches))
    parts.append("")
    parts.append(block("مباريات قادمة", later_matches[:30]))
    parts.append("")
    parts.append("📺 البث والقنوات الناقلة يتم إضافتها من الإدارة عند التوفر.\n"
                 "📣 لمتابعة أخبار كرة القدم لحظة بلحظة: @F90Sports")

    return "\n".join(parts)


def send_global_schedule():
    """نشر جدول عام للمباريات القادمة."""
    fixtures = fetch_next_fixtures(limit=60)
    if not fixtures:
        tg_send_message("📆 لا توجد مباريات قادمة متاحة حالياً (أو خطأ من المزود).")
        return
    msg = group_schedule_text(fixtures)
    tg_send_message(msg)


# ============================
#   جدول خاص للفرق الكبيرة
# ============================

def send_favorites_schedule():
    """نشر جدول خاص لأقرب مباراة لكل فريق من FAVORITE_TEAMS."""
    fixtures = fetch_next_fixtures(limit=200)
    if not fixtures:
        return

    team_next = {name: None for name in FAVORITE_TEAMS}

    for fx in fixtures:
        f = fx["fixture"]
        t = fx["teams"]
        home = t["home"]["name"]
        away = t["away"]["name"]

        for name in FAVORITE_TEAMS:
            if name.lower() in home.lower() or name.lower() in away.lower():
                # لو لسه ما حطينا مباراة لهذا الفريق
                if team_next[name] is None:
                    team_next[name] = fx

    lines = ["🔥 <b>أقرب مباريات الفرق الكبيرة (VIP)</b>\n"]
    any_match = False

    for name, fx in team_next.items():
        if not fx:
            continue
        any_match = True
        f = fx["fixture"]
        l = fx["league"]
        t = fx["teams"]

        home = t["home"]["name"]
        away = t["away"]["name"]
        league_name = l["name"]
        time_str = utc_to_local_str(f["date"])

        lines.append(f"⭐ <b>{name}</b>")
        lines.append(f"🏟 {home} vs {away}")
        lines.append(f"🏆 {league_name}")
        lines.append(f"⏰ {time_str}")
        lines.append("")

    if not any_match:
        lines.append("لا توجد مباريات قادمة حالياً لهذه الفرق.")
    else:
        lines.append("📺 روابط البث تُضاف من الإدارة عند التوفر.")

    tg_send_message("\n".join(lines))


# ============================
#   هدافي الدوريات
# ============================

def send_top_scorers():
    """نشر هدافي أهم الدوريات."""
    msg_parts = ["⚽️ <b>قائمة الهدافين (إحصائيات تقريبية)</b>\n"]

    for league_id in IMPORTANT_LEAGUES[:5]:  # نكتفي بـ 5 دوريات
        data = api_football_get(
            "/players/topscorers",
            params={"league": league_id, "season": datetime.utcnow().year},
        )
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
    """اختيار مباراة قوية من المباريات القادمة كـ 'مباراة الأسبوع'."""
    fixtures = fetch_next_fixtures(limit=80)
    if not fixtures:
        return None

    # أولوية للفرق الكبيرة
    vip_matches = [f for f in fixtures if is_favorite_match(f)]
    if vip_matches:
        return vip_matches[0]

    # أولوية للدوريات الكبيرة
    for fx in fixtures:
        league_name = fx["league"]["name"].lower()
        if any(k in league_name for k in ["champions", "الدوري", "league"]):
            return fx

    return fixtures[0]


def simple_predict(home_name: str, away_name: str) -> str:
    """توقع بسيط جداً لأجل الشكل."""
    big = [
        "real madrid",
        "barcelona",
        "manchester city",
        "bayern",
        "liverpool",
        "al nassr",
        "al hilal",
        "al ittihad",
    ]
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
        return "🧠 التوقع: مباراة متقاربة جداً، الفرص متساوية."


def send_match_of_week():
    fx = pick_match_of_week()
    if not fx:
        print("لا توجد مباراة أسبوع مناسبة.")
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

live_state: dict[int, dict] = {}   # fixture_id -> {score_home, score_away, status}
seen_events: set[str] = set()
pre_alerts: dict[int, dict] = {}   # fixture_id -> {"10":bool, "5":bool}


def fetch_live_fixtures() -> list[dict]:
    data = api_football_get("/fixtures", params={"live": "all", "timezone": "UTC"})
    return data.get("response", [])


def fetch_fixture_events(fixture_id: int) -> list[dict]:
    data = api_football_get("/fixtures/events", params={"fixture": fixture_id})
    return data.get("response", [])


def fetch_fixture_stats(fixture_id: int) -> list[dict]:
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
        dt_utc = datetime.fromisoformat(date_iso.replace("Z", "+00:00")).replace(
            tzinfo=timezone.utc
        )
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


def format_half_stats(stats_resp: list[dict]) -> str:
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
            if t in [
                "Shots on Goal",
                "Total Shots",
                "Ball Possession",
                "Yellow Cards",
                "Red Cards",
            ]:
                lines.append(f"- {t}: {v}")
    return "\n".join(lines)


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

            # تغيير حالة المباراة
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
                elif status_short == "FT":
                    tg_send_message("🏁 <b>نهاية المباراة</b>\n" + header)
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
#   حلقة التشغيل الرئيسية
# ============================

def run_loop():
    print("🚀 F90 Sports Live Bot started...")
    last_schedule = 0
    last_topscorers = 0
    last_match_of_week = 0
    last_favorites = 0

    while True:
        now = time.time()

        # 1) جدول عام للمباريات القادمة
        if now - last_schedule > SCHEDULE_EVERY_SECONDS:
            try:
                send_global_schedule()
            except Exception as e:
                print("Schedule error:", e)
            last_schedule = now

        # 2) جدول خاص للفرق الكبيرة
        if now - last_favorites > FAVORITES_EVERY_SECONDS:
            try:
                send_favorites_schedule()
            except Exception as e:
                print("Favorites error:", e)
            last_favorites = now

        # 3) هدافين الدوريات
        if now - last_topscorers > TOPSCORERS_EVERY_SECONDS:
            try:
                send_top_scorers()
            except Exception as e:
                print("Topscorers error:", e)
            last_topscorers = now

        # 4) مباراة الأسبوع
        if now - last_match_of_week > MATCH_OF_WEEK_EVERY_SECONDS:
            try:
                send_match_of_week()
            except Exception as e:
                print("Match-of-week error:", e)
            last_match_of_week = now

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
