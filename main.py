import os
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask

# ============================
#   إعدادات أساسية
# ============================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID", "@F90Sports")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")

if not BOT_TOKEN or not API_FOOTBALL_KEY:
    print("❌ BOT_TOKEN أو API_FOOTBALL_KEY غير مضبوطين في Environment Variables!")

# توقيت القدس (تقريبي UTC+2)
TZ_OFFSET = 2

# إعدادات تكرار
LIVE_POLL_SECONDS = 60                # فحص لايف كل 60 ثانية
SCHEDULE_EVERY_SECONDS = 1800         # جدول كل 30 دقيقة
TOPSCORERS_EVERY_SECONDS = 12 * 3600  # هدافين كل 12 ساعة
MATCH_OF_WEEK_EVERY_SECONDS = 12 * 3600  # مباراة الأسبوع كل 12 ساعة
STANDINGS_EVERY_SECONDS = 3600        # ترتيب النقاط كل ساعة

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

# الموسم الصحيح تلقائيًا (تقريبي: من أغسطس يبدأ موسم جديد)
today_date = datetime.utcnow().date()
CURRENT_SEASON = today_date.year if today_date.month >= 8 else today_date.year - 1

# فرق VIP برسائل خاصة
FAVORITE_TEAMS = [
    "Real Madrid",
    "Barcelona",
    "Al Nassr",
    "Al Ittihad",
]

# Footer موحّد لكل الرسائل
FOOTER = (
    "\n\n——————————————\n"
    "📡 قناة الرياضة: @F90Sports\n"
    "📰 قناة الأخبار: @f90newsnow\n"
)

# لتجميع نتائج اليوم للملخص اليومي
daily_results = {}   # { 'YYYY-MM-DD': [ {league, home, away, score} ] }
current_local_day = None  # سيتم ضبطه في البداية


# ============================
#   أدوات عامة
# ============================

def tg_send_message(text, add_footer=True):
    """إرسال نص لتلجرام."""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN مفقود.")
        return
    if add_footer:
        text = text + FOOTER
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
        if r.status_code != 200:
            print("Telegram sendMessage error:", r.text)
    except Exception as e:
        print("Telegram sendMessage exception:", e)


def tg_send_photo(photo_url, caption, add_footer=True):
    """إرسال صورة + كابشن. لو فشل، يرسل نص فقط."""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN مفقود.")
        return
    if add_footer:
        caption = caption + FOOTER
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        r = requests.post(
            url,
            data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML", "photo": photo_url},
            timeout=20,
        )
        if r.status_code != 200:
            print("Telegram sendPhoto error:", r.text)
            # fallback
            tg_send_message(caption, add_footer=False)
    except Exception as e:
        print("Telegram sendPhoto exception:", e)
        tg_send_message(caption, add_footer=False)


def api_football_get(path, params=None):
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


def utc_to_local_str(iso_str):
    """تحويل وقت ISO إلى نص بالعربية بتوقيت القدس تقريبياً."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
        dt_local = dt + timedelta(hours=TZ_OFFSET)
        return dt_local.strftime("%Y-%m-%d • %H:%M")
    except Exception:
        return iso_str


def utc_to_local_date_str(iso_str):
    """إرجاع تاريخ محلي (YYYY-MM-DD) من وقت ISO."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
        dt_local = dt + timedelta(hours=TZ_OFFSET)
        return dt_local.date().isoformat()
    except Exception:
        return datetime.utcnow().date().isoformat()


def is_favorite_match(fixture):
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

def fetch_fixtures_for_dates(date_from, date_to):
    fixtures = []

    for league_id in IMPORTANT_LEAGUES:
        params = {
            "from": date_from,
            "to": date_to,
            "league": league_id,
            "season": CURRENT_SEASON,
            "timezone": "UTC",
        }
        data = api_football_get("/fixtures", params=params)
        fixtures.extend(data.get("response", []))

    return fixtures


def group_text(title, fixtures):
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
        lines.append(f"🏟 {home} vs {away}\n   🏆 {league_name}\n   ⏰ {time_str}")
    return "\n".join(lines)


def build_schedule_message():
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
        "",
        "📺 البث والقنوات الناقلة يتم إضافتها من الإدارة عند التوفر."
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

        logo = t["home"].get("logo") or t["away"].get("logo")
        if logo:
            tg_send_photo(logo, caption, add_footer=True)
        else:
            tg_send_message(caption)


# ============================
#   هدافي الدوريات (Top Scorers)
# ============================

def send_top_scorers():
    """نشر هدافي أهم الدوريات."""
    msg_parts = ["⚽️ <b>قائمة الهدافين (إحصائيات تقريبية)</b>\n"]

    for league_id in IMPORTANT_LEAGUES[:5]:  # نكتفي بـ 5 دوريات
        data = api_football_get("/players/topscorers", params={
            "league": league_id,
            "season": CURRENT_SEASON,
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

    vip_matches = [f for f in fixtures_week if is_favorite_match(f)]
    if vip_matches:
        return vip_matches[0]

    for fx in fixtures_week:
        league_name = fx["league"]["name"].lower()
        if any(k in league_name for k in ["champions"]):
            return fx

    return fixtures_week[0]


def simple_predict(home_name, away_name):
    """توقع بسيط (ديكور فقط)."""
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
        return "🧠 التوقع: مباراة متقاربة جداً، الفرص متساوية."


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
        tg_send_photo(logo, txt, add_footer=True)
    else:
        tg_send_message(txt)


# ============================
#   لايف: أهداف + كروت + تبديلات
# ============================

live_state = {}      # fixture_id -> {score_home, score_away, status}
seen_events = set()
pre_alerts = {}      # fixture_id -> {"10":bool, "5":bool}


def fetch_live_fixtures():
    data = api_football_get("/fixtures", params={"live": "all", "timezone": "UTC"})
    return data.get("response", [])


def fetch_fixture_events(fixture_id):
    data = api_football_get("/fixtures/events", params={"fixture": fixture_id})
    return data.get("response", [])


def fetch_fixture_stats(fixture_id):
    data = api_football_get("/fixtures/statistics", params={"fixture": fixture_id})
    return data.get("response", [])


def ensure_pre_alerts(fixture_id):
    if fixture_id not in pre_alerts:
        pre_alerts[fixture_id] = {"10": False, "5": False}


def check_and_send_pre_match_alerts(fx):
    """تنبيه قبل 10 دقائق و5 دقائق من البداية (لأي مباراة مهمة)."""
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

    if 5 < minutes_to_ko <= 10 and not pre_alerts[fixture_id]["10"]:
        tg_send_message("⏳ <b>بعد 10 دقائق تنطلق مباراة:</b>\n" + base_txt)
        pre_alerts[fixture_id]["10"] = True

    if 0 < minutes_to_ko <= 5 and not pre_alerts[fixture_id]["5"]:
        tg_send_message("⏳ <b>بعد 5 دقائق تنطلق مباراة:</b>\n" + base_txt)
        pre_alerts[fixture_id]["5"] = True


def format_live_header(fx):
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


def format_half_stats(stats_resp):
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


def extract_goals_summary(events):
    """إرجاع ملخص بسيط للأهداف من قائمة الأحداث."""
    goals_lines = []
    for ev in events:
        if ev.get("type") != "Goal":
            continue
        minute = ev.get("time", {}).get("elapsed")
        team_name = ev.get("team", {}).get("name", "")
        player = ev.get("player", {}).get("name", "")
        detail = ev.get("detail", "")
        line = f"⚽️ {minute}' – {team_name} – {player}"
        if detail:
            line += f" ({detail})"
        goals_lines.append(line)
    if not goals_lines:
        return "⚽️ لم تسجّل أهداف (أو لا تتوفر بيانات مفصلة)."
    return "\n".join(goals_lines)


def process_live_fixtures():
    global live_state, daily_results

    live = fetch_live_fixtures()
    if not live:
        print("لا توجد مباريات جارية الآن.")
        return

    for fx in live:
        f = fx["fixture"]
        fixture_id = f["id"]

        check_and_send_pre_match_alerts(fx)

        prev = live_state.get(fixture_id)
        goals = fx["goals"]
        score_home = goals["home"]
        score_away = goals["away"]
        status_short = f["status"]["short"]

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
            # هدف جديد
            if score_home != prev["score_home"] or score_away != prev["score_away"]:
                header = format_live_header(fx)
                if is_favorite_match(fx):
                    tg_send_message("⚽️ <b>هدف في مباراة فريقك المفضل!</b>\n" + header)
                else:
                    tg_send_message("⚽️ <b>هدف جديد!</b>\n" + header)

                prev["score_home"] = score_home
                prev["score_away"] = score_away

            # تغيير حالة المباراة (HT, FT,...)
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

                    # ملخص كامل بعد نهاية المباراة
                    try:
                        events = fetch_fixture_events(fixture_id)
                        goals_txt = extract_goals_summary(events)
                        stats = fetch_fixture_stats(fixture_id)
                        stats_txt = format_half_stats(stats)

                        summary = (
                            "📊 <b>ملخص المباراة (نهائي)</b>\n\n"
                            + header + "\n\n"
                            + goals_txt + "\n\n"
                            + stats_txt
                        )
                        tg_send_message(summary)
                    except Exception as e:
                        print("Post-match summary error:", e)

                    # حفظ النتيجة لملخص اليوم
                    local_day = utc_to_local_date_str(f["date"])
                    league_name = fx["league"]["name"]
                    home = fx["teams"]["home"]["name"]
                    away = fx["teams"]["away"]["name"]
                    score_str = f"{goals['home']} - {goals['away']}"
                    daily_results.setdefault(local_day, []).append({
                        "league": league_name,
                        "home": home,
                        "away": away,
                        "score": score_str,
                    })

                else:
                    tg_send_message("🔄 <b>تحديث حالة المباراة</b>\n" + header)

                prev["status"] = status_short

        # أحداث تفصيلية: أهداف، بطاقات، تبديلات
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
#   ترتيب النقاط (Standings)
# ============================

def fetch_standings(league_id):
    data = api_football_get("/standings", params={
        "league": league_id,
        "season": CURRENT_SEASON,
    })
    resp = data.get("response", [])
    if not resp:
        return None
    league = resp[0]["league"]
    name = league["name"]
    table = league["standings"][0]  # أول مجموعة (غالباً مجموعة واحدة)
    return name, table


def send_all_standings():
    lines = ["📊 <b>ترتيب أهم الدوريات (تقريبي)</b>\n"]
    for league_id in IMPORTANT_LEAGUES[:6]:
        try:
            result = fetch_standings(league_id)
            if not result:
                continue
            league_name, table = result
            lines.append(f"🏆 <b>{league_name}</b>")
            for row in table[:5]:
                rank = row["rank"]
                team = row["team"]["name"]
                pts = row["points"]
                played = row["all"]["played"]
                gd = row["goalsDiff"]
                lines.append(f"{rank}. {team} – {pts} نقطة (مباريات: {played}، فارق: {gd})")
            lines.append("")
        except Exception as e:
            print("Standings error:", e)

    if len(lines) > 1:
        tg_send_message("\n".join(lines))


# ============================
#   ملخص يومي للمباريات
# ============================

def send_daily_summary_for_day(day_str):
    """إرسال ملخص نهائي لكل مباريات يوم معيّن."""
    results = daily_results.get(day_str, [])
    if not results:
        print(f"📭 لا توجد نتائج مسجّلة لليوم {day_str}")
        return

    lines = [f"📊 <b>ملخص مباريات يوم {day_str} (بتوقيت القدس)</b>\n"]
    # تجميع حسب الدوري
    by_league = {}
    for r in results:
        by_league.setdefault(r["league"], []).append(r)

    total_matches = 0
    for league_name, matches in by_league.items():
        lines.append(f"🏆 <b>{league_name}</b>")
        for m in matches:
            lines.append(f"• {m['home']} {m['score']} {m['away']}")
            total_matches += 1
        lines.append("")

    lines.append(f"📌 إجمالي المباريات التي تم لعبها اليوم: {total_matches}")
    tg_send_message("\n".join(lines))


# ============================
#   حلقة التشغيل الرئيسية
# ============================

def run_loop():
    global current_local_day

    print("🚀 F90 Sports Live Bot started...")

    # ضبط اليوم الحالي بتوقيت القدس
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    now_local = now_utc + timedelta(hours=TZ_OFFSET)
    current_local_day = now_local.date()

    last_schedule = 0
    last_topscorers = 0
    last_match_of_week = 0
    last_standings = 0

    while True:
        now = time.time()

        # فحص تغيّر اليوم لإرسال ملخص اليوم السابق
        now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
        now_local = now_utc + timedelta(hours=TZ_OFFSET)
        today_local = now_local.date()
        if today_local != current_local_day:
            prev_day_str = current_local_day.isoformat()
            send_daily_summary_for_day(prev_day_str)
            current_local_day = today_local

        # 1) جدول المباريات + بوسترات VIP كل نصف ساعة
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

        # 3) مباراة الأسبوع كل 12 ساعة تقريباً
        if now - last_match_of_week > MATCH_OF_WEEK_EVERY_SECONDS:
            try:
                send_match_of_week()
            except Exception as e:
                print("Match-of-week error:", e)
            last_match_of_week = now

        # 4) ترتيب النقاط كل ساعة
        if now - last_standings > STANDINGS_EVERY_SECONDS:
            try:
                send_all_standings()
            except Exception as e:
                print("Standings loop error:", e)
            last_standings = now

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
