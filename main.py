import os
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask

# ============================
#   الإعدادات العامة
# ============================

# ضبّط هذه القيم في Render → Environment
BOT_TOKEN = os.getenv("BOT_TOKEN", "8278742496:AAH8lDMB0ci6mX0I7JIiIbuB8ZudyWVqT3E")
CHAT_ID = os.getenv("CHAT_ID", "@F90Sports")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "f75265ca25cdfb56f0907dfff86d1226")

if not BOT_TOKEN or not API_FOOTBALL_KEY:
    print("❌ BOT_TOKEN أو API_FOOTBALL_KEY غير مضبوطين! تأكد من Environment Variables في Render.")

# توقيت القدس (تقريبياً +2)
TZ_OFFSET = 2

# تكرار الوظائف
LIVE_POLL_SECONDS = 60             # فحص المباريات اللايف كل 60 ثانية
SCHEDULE_EVERY_SECONDS = 1800      # جدول اليوم/الغد/الأسبوع كل 30 دقيقة
TOPSCORERS_EVERY_SECONDS = 12*3600 # هدافي الدوريات كل 12 ساعة
MATCH_OF_WEEK_EVERY_SECONDS = 12*3600  # مباراة الأسبوع كل 12 ساعة
VIP_NEXT_EVERY_SECONDS = 3600      # جدول "المباريات القادمة للفرق الكبيرة" كل ساعة

# الدوريات المهمة
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

# فرق مهمة (نعتمد على الاسم في الـ API)
VIP_TEAMS = [
    "Real Madrid",
    "Barcelona",
    "Atletico Madrid",
    "Liverpool",
    "Chelsea",
    "Manchester City",
    "Manchester United",
    "Bayern Munich",
    "Paris Saint Germain",
    "Al Nassr",
    "Al Hilal",
]

# ترجمة ودّية للأسماء بالعربي (للعرض فقط)
VIP_NAME_AR = {
    "Real Madrid": "ريال مدريد",
    "Barcelona": "برشلونة",
    "Atletico Madrid": "أتلتيكو مدريد",
    "Liverpool": "ليفربول",
    "Chelsea": "تشيلسي",
    "Manchester City": "مانشستر سيتي",
    "Manchester United": "مانشستر يونايتد",
    "Bayern Munich": "بايرن ميونخ",
    "Paris Saint Germain": "باريس سان جيرمان",
    "Al Nassr": "النصر",
    "Al Hilal": "الهلال",
}

# تذييل ثابت يربط قناة الرياضة مع قناة الأخبار
FOOTER = (
    "\n\n────────────────\n"
    "📡 شبكتنا:\n"
    "⚽️ قناة الرياضة: @F90Sports\n"
    "📰 قناة الأخبار: @f90newsnow\n"
)

# ============================
#   دوال Telegram
# ============================

def tg_send_message(text: str):
    """إرسال نص لتلجرام مع ParseMode=HTML."""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN مفقود.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": text + FOOTER, "parse_mode": "HTML"},
            timeout=20,
        )
        if r.status_code != 200:
            print("Telegram sendMessage error:", r.text)
    except Exception as e:
        print("Telegram sendMessage exception:", e)


def tg_send_photo(photo_url: str, caption: str):
    """
    إرسال صورة بكابشن. نمرّر رابط الصورة مباشرة.
    لو فشل، نرسل الكابشن كنص فقط.
    """
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN مفقود.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        r = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "caption": caption + FOOTER,
                "parse_mode": "HTML",
                "photo": photo_url,
            },
            timeout=20,
        )
        if r.status_code != 200:
            print("Telegram sendPhoto error:", r.text)
            tg_send_message(caption)  # fallback
    except Exception as e:
        print("Telegram sendPhoto exception:", e)
        tg_send_message(caption)


# ============================
#   API-FOOTBALL
# ============================

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
    """تحويل وقت ISO لوقت نصي بتوقيت القدس."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).replace(
            tzinfo=timezone.utc
        )
        dt_local = dt + timedelta(hours=TZ_OFFSET)
        return dt_local.strftime("%Y-%m-%d • %H:%M")
    except Exception:
        return iso_str


def is_favorite_match(fixture: dict) -> bool:
    """هل المباراة تخص فريق من VIP_TEAMS؟"""
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    for name in VIP_TEAMS:
        if name.lower() in home.lower() or name.lower() in away.lower():
            return True
    return False


# ============================
#   جدول المباريات (اليوم/غداً/الأسبوع)
# ============================

def fetch_fixtures_for_dates(date_from: str, date_to: str) -> list:
    fixtures = []
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


def format_group_block(title: str, fixtures: list) -> str:
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
        format_group_block("مباريات اليوم", fixtures_today),
        "",
        format_group_block("مباريات الغد", fixtures_tomorrow),
        "",
        format_group_block("هذا الأسبوع (أهم المباريات)", fixtures_week),
        "",
        "📺 البث والقنوات الناقلة يتم إضافتها من الإدارة عند التوفر.",
    ]
    return "\n".join(msg_parts), fixtures_today


def send_schedule_text_and_vip_posters():
    msg, fixtures_today = build_schedule_message()
    tg_send_message(msg)

    # بوسترات خاصة لمباريات VIP اليوم
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
            "📺 البث: يتم إضافة الرابط من الإدارة عند التوفر.\n"
            "📣 قناة الرياضة: @F90Sports"
        )

        logo = t["home"].get("logo") or t["away"].get("logo")
        if logo:
            tg_send_photo(logo, caption)
        else:
            tg_send_message(caption)


# ============================
#   جدول "أقرب مباراة" للفرق الكبيرة
# ============================

def build_vip_next_matches_message():
    """
    يبحث عن أقرب مباراة قادمة لكل فريق من VIP_TEAMS
    ضمن حدود (اليوم → بعد 30 يوم)، ويرسلها مرتبة حسب الأقرب.
    """
    today = datetime.utcnow().date()
    limit = today + timedelta(days=30)

    fixtures_range = fetch_fixtures_for_dates(str(today), str(limit))
    if not fixtures_range:
        return None

    # نحفظ أقرب مباراة لكل فريق
    vip_next = {}  # team_en -> fixture

    for fx in fixtures_range:
        f = fx["fixture"]
        date_iso = f.get("date")
        if not date_iso:
            continue
        try:
            dt_utc = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
        except Exception:
            continue

        # لو المباراة في الماضي نتجاهلها
        if dt_utc < datetime.utcnow():
            continue

        home_name = fx["teams"]["home"]["name"]
        away_name = fx["teams"]["away"]["name"]

        for vip_en in VIP_TEAMS:
            if vip_en.lower() in home_name.lower() or vip_en.lower() in away_name.lower():
                prev_fx = vip_next.get(vip_en)
                if not prev_fx:
                    vip_next[vip_en] = fx
                else:
                    # لو هذه أقرب للآن من السابقة
                    try:
                        prev_date = datetime.fromisoformat(
                            prev_fx["fixture"]["date"].replace("Z", "+00:00")
                        )
                    except Exception:
                        prev_date = dt_utc + timedelta(days=999)
                    if dt_utc < prev_date:
                        vip_next[vip_en] = fx

    if not vip_next:
        return None

    # نرتّب VIP حسب موعد المباراة الأقرب
    sorted_items = []
    for vip_en, fx in vip_next.items():
        try:
            dt_utc = datetime.fromisoformat(
                fx["fixture"]["date"].replace("Z", "+00:00")
            )
        except Exception:
            dt_utc = datetime.utcnow() + timedelta(days=999)
        sorted_items.append((vip_en, fx, dt_utc))

    sorted_items.sort(key=lambda x: x[2])

    lines = [
        "📅 <b>أقرب مباريات الفرق الكبيرة (الشهر القادم)</b>\n",
        "يتم تحديث هذه القائمة تلقائياً كل ساعة حتى لو الموعد بعيد.\n",
    ]

    for vip_en, fx, dt_utc in sorted_items:
        f = fx["fixture"]
        l = fx["league"]
        t = fx["teams"]

        home = t["home"]["name"]
        away = t["away"]["name"]
        league_name = l["name"]
        time_str = utc_to_local_str(f["date"])
        vip_ar = VIP_NAME_AR.get(vip_en, vip_en)

        lines.append(
            f"⭐️ <b>{vip_ar}</b>\n"
            f"🏟 {home} vs {away}\n"
            f"🏆 {league_name}\n"
            f"⏰ {time_str}\n"
        )

    return "\n".join(lines)


def send_vip_next_matches():
    text = build_vip_next_matches_message()
    if text:
        tg_send_message(text)
    else:
        print("لا توجد مباريات قادمة للفرق الكبيرة في الفترة المحددة.")


# ============================
#   هدافي الدوريات
# ============================

def send_top_scorers():
    msg_parts = ["⚽️ <b>قوائم الهدافين لأهم الدوريات</b>\n"]

    for league_id in IMPORTANT_LEAGUES[:5]:  # نكتفي بـ5 دوريات
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
    today = datetime.utcnow().date()
    week_later = today + timedelta(days=7)
    fixtures_week = fetch_fixtures_for_dates(str(today), str(week_later))
    if not fixtures_week:
        return None

    vip_matches = [f for f in fixtures_week if is_favorite_match(f)]
    if vip_matches:
        return vip_matches[0]

    for fx in fixtures_week:
        league_name = fx["league"]["name"].lower()
        if "champions" in league_name:
            return fx

    return fixtures_week[0]


def simple_predict(home_name: str, away_name: str) -> str:
    big = [
        "real madrid", "barcelona", "manchester city",
        "bayern", "liverpool", "al nassr", "al hilal"
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
        return "🧠 التوقع: مباراة متقاربة جداً والفرص متساوية."


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

    text = (
        "💥 <b>مباراة الأسبوع – F90 Sports</b>\n\n"
        f"🏟 {home} vs {away}\n"
        f"🏆 {league_name}\n"
        f"⏰ {time_str}\n\n"
        f"{simple_predict(home, away)}\n\n"
        "📺 البث والقنوات الناقلة يتم إضافتها عند التوفر."
    )

    logo = t["home"].get("logo") or t["away"].get("logo")
    if logo:
        tg_send_photo(logo, text)
    else:
        tg_send_message(text)


# ============================
#   بث لايف: أهداف + كروت + تبديلات
# ============================

live_state = {}      # fixture_id -> {score_home, score_away, status}
seen_events = set()
pre_alerts = {}      # fixture_id -> {"10":bool, "5":bool}


def fetch_live_fixtures() -> list:
    data = api_football_get("/fixtures", params={"live": "all", "timezone": "UTC"})
    return data.get("response", [])


def fetch_fixture_events(fixture_id: int) -> list:
    data = api_football_get("/fixtures/events", params={"fixture": fixture_id})
    return data.get("response", [])


def fetch_fixture_stats(fixture_id: int) -> list:
    data = api_football_get("/fixtures/statistics", params={"fixture": fixture_id})
    return data.get("response", [])


def ensure_pre_alerts(fid: int):
    if fid not in pre_alerts:
        pre_alerts[fid] = {"10": False, "5": False}


def check_and_send_pre_match_alerts(fx: dict):
    """تنبيه قبل 10 دقائق و5 دقائق من بداية المباراة."""
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

    if 5 < minutes_to_ko <= 10 and not pre_alerts[fixture_id]["10"]:
        tg_send_message("⏳ <b>بعد 10 دقائق تنطلق مباراة:</b>\n" + base_txt)
        pre_alerts[fixture_id]["10"] = True

    if 0 < minutes_to_ko <= 5 and not pre_alerts[fixture_id]["5"]:
        tg_send_message("⏳ <b>بعد 5 دقائق تنطلق مباراة:</b>\n" + base_txt)
        pre_alerts[fixture_id]["5"] = True


def format_live_header(fx: dict) -> str:
    f = fx["fixture"]
    l = fx["league"]
    t = fx["teams"]
    g = fx["goals"]

    home = t["home"]["name"]
    away = t["away"]["name"]
    league_name = l["name"]
    status = f["status"]["long"]
    elapsed = f["status"]["elapsed"]
    score = f"{g['home']} - {g['away']}"
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
            if t in ["Shots on Goal", "Total Shots", "Ball Possession",
                     "Shots off Goal", "Yellow Cards", "Red Cards"]:
                lines.append(f"- {t}: {v}")
    return "\n".join(lines)


def process_live_fixtures():
    global live_state, seen_events

    live = fetch_live_fixtures()
    if not live:
        print("لا توجد مباريات جارية الآن.")
        return

    for fx in live:
        f = fx["fixture"]
        fixture_id = f["id"]

        # تنبيه قبل المباراة (لو كانت قريبة من البدء)
        check_and_send_pre_match_alerts(fx)

        prev = live_state.get(fixture_id)
        goals = fx["goals"]
        score_home = goals["home"]
        score_away = goals["away"]
        status_short = f["status"]["short"]  # 1H, HT, 2H, FT...

        # أول مرة نرى المباراة
        if not prev:
            header = format_live_header(fx)
            if is_favorite_match(fx):
                tg_send_message("🎬 <b>انطلاق مباراة مهمة لفريقك المفضل!</b>\n" + header)
            else:
                tg_send_message("🎬 <b>انطلاق مباراة جديدة</b>\n" + header)

            live_state[fixture_id] = {
                "score_home": score_home,
                "score_away": score_away,
                "status": status_short,
            }
        else:
            # هدف جديد
            if score_home != prev["score_home"] or score_away != prev["score_away"]:
                header = format_live_header(fx)
                if is_favorite_match(fx):
                    tg_send_message("⚽️ <b>هدف في مباراة فريقك المفضل!</b>\n" + header)
                else:
                    tg_send_message("⚽️ <b>هدف جديد!</b>\n" + header)

                prev["score_home"] = score_home
                prev["score_away"] = score_away

            # تغيير في الحالة
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

        # أحداث المباراة (أهداف/كروت/تبديل)
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
    last_vip_next = 0

    while True:
        now = time.time()

        # 1) جدول اليوم/الغد/الأسبوع + بوسترات VIP
        if now - last_schedule > SCHEDULE_EVERY_SECONDS:
            try:
                send_schedule_text_and_vip_posters()
            except Exception as e:
                print("Schedule error:", e)
            last_schedule = now

        # 2) هدافي الدوريات
        if now - last_topscorers > TOPSCORERS_EVERY_SECONDS:
            try:
                send_top_scorers()
            except Exception as e:
                print("Top scorers error:", e)
            last_topscorers = now

        # 3) مباراة الأسبوع
        if now - last_match_of_week > MATCH_OF_WEEK_EVERY_SECONDS:
            try:
                send_match_of_week()
            except Exception as e:
                print("Match of week error:", e)
            last_match_of_week = now

        # 4) أقرب مباراة للفرق الكبيرة
        if now - last_vip_next > VIP_NEXT_EVERY_SECONDS:
            try:
                send_vip_next_matches()
            except Exception as e:
                print("VIP next matches error:", e)
            last_vip_next = now

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
