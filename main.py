import feedparser
import requests
import time
import re
from html import unescape
import os
import threading
from datetime import datetime, timedelta, date
from flask import Flask

# ============================
#   إعدادات عامة
# ============================

# توكن بوت الرياضة (من BotFather)
BOT_TOKEN = os.getenv("BOT_TOKEN", "8349529503:AAGj-SNuDNuhxmb22J13L9fkH_9DE1FFlIg")

# قناة النشر
CHAT_ID = os.getenv("CHAT_ID", "@F90Sports")

# مفتاح API-Football (من API-SPORTS)
API_FOOTBALL_KEY = os.getenv(
    "API_FOOTBALL_KEY",
    "3caa9eece931b202667d7c0e71ebe84918e5ac75adc7669ea0522ef241326e6f"
)

# مصادر أخبار رياضية (RSS)
SPORTS_SOURCES = [
    "https://www.skysports.com/rss/12040",              # Sky Sports Football
    "https://www.espn.com/espn/rss/soccer/news",        # ESPN Soccer
    "https://www.goal.com/feeds/en/news",               # Goal.com
]

FOOTER = (
    "\n\n———\n"
    "📢 تابعوا شبكة F90 لحظة بلحظة\n"
    "📡 قناة الرياضة: @F90Sports\n"
    "📡 قناة الأخبار العامة: @f90newsnow"
)

# تتبع منع التكرار
seen_news_links = set()
seen_news_titles = set()
sent_fixture_schedules = set()
sent_fixture_results = set()
last_fixture_state = {}  # fixture_id -> (status_short, home_goals, away_goals)

current_day = date.today()

# ============================
#   أدوات مساعدة عامة
# ============================

def clean_html(raw: str) -> str:
    if not raw:
        return ""
    raw = unescape(raw)
    raw = re.sub(r"<[^>]+>", " ", raw)     # إزالة HTML
    raw = re.sub(r"http\S+", "", raw)      # إزالة الروابط
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw

def get_full_text(entry) -> str:
    if "summary" in entry:
        return clean_html(entry.summary)
    if "description" in entry:
        return clean_html(entry.description)
    return ""

def get_image(entry):
    for key in ("media_content", "media_thumbnail", "enclosures"):
        if key in entry:
            try:
                data = entry[key][0] if isinstance(entry[key], list) else entry[key]
                url = data.get("url") or data.get("href")
                if url and url.startswith("http") and not url.endswith(".mp4"):
                    return url
            except Exception:
                pass
    return None

def send_text_to_channel(text: str):
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN غير مضبوط، لن يتم الإرسال.")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print("⚠️ خطأ في إرسال رسالة تيليجرام:", e)

# ============================
#   أخبار رياضية من RSS
# ============================

def send_sports_news(title, source, details, img=None):
    caption = (
        f"⚽ <b>{title}</b>\n\n"
        f"{details}\n\n"
        f"📰 <i>{source}</i>"
        f"{FOOTER}"
    )

    if img:
        try:
            pdata = requests.get(img, timeout=10).content
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": pdata}
            )
            return
        except Exception as e:
            print("⚠️ فشل إرسال صورة الخبر الرياضي:", e)

    send_text_to_channel(caption)

def process_sports_rss():
    new_count = 0
    for url in SPORTS_SOURCES:
        try:
            feed = feedparser.parse(url)
            source = feed.feed.get("title", "Sports")

            for entry in reversed(feed.entries):
                link = entry.get("link", "")
                if not link or link in seen_news_links:
                    continue

                title = clean_html(entry.get("title", "خبر رياضي"))
                if not title or title in seen_news_titles:
                    continue

                details = get_full_text(entry)
                if len(details) < 40:
                    continue

                img = get_image(entry)

                send_sports_news(title, source, details, img)

                seen_news_links.add(link)
                seen_news_titles.add(title)
                new_count += 1

                time.sleep(1)

        except Exception as e:
            print("⚠️ خطأ في RSS:", e)

    if new_count == 0:
        print("⏸️ لا أخبار رياضية جديدة الآن من RSS.")

# ============================
#   API-Football للمباريات
# ============================

def api_get(path, params=None):
    if not API_FOOTBALL_KEY:
        return None
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    try:
        r = requests.get(
            "https://v3.football.api-sports.io" + path,
            headers=headers,
            params=params,
            timeout=15
        )
        if r.status_code != 200:
            print("⚠️ خطأ من API-Football:", r.status_code, r.text[:200])
            return None
        return r.json()
    except Exception as e:
        print("⚠️ استثناء API-Football:", e)
        return None

def status_to_ar(short):
    mapping = {
        "NS": "لم تبدأ بعد",
        "TBD": "الوقت لم يُحدّد",
        "1H": "الشوط الأول",
        "HT": "استراحة بين الشوطين",
        "2H": "الشوط الثاني",
        "ET": "وقت إضافي",
        "P": "ركلات ترجيح",
        "FT": "انتهت المباراة",
        "AET": "انتهت بعد وقت إضافي",
        "PEN": "انتهت بركلات الترجيح",
        "SUSP": "موقوفة",
        "PST": "مؤجّلة",
        "CANC": "ألغيت",
    }
    return mapping.get(short, short or "غير معروف")

def format_fixture_lines(fix):
    fixture = fix.get("fixture", {})
    league = fix.get("league", {})
    teams = fix.get("teams", {})
    goals = fix.get("goals", {})

    home = teams.get("home", {}).get("name", "الفريق المضيف")
    away = teams.get("away", {}).get("name", "الفريق الضيف")
    hg = goals.get("home")
    ag = goals.get("away")

    status_obj = fixture.get("status", {})
    status_short = status_obj.get("short", "")
    status_ar = status_to_ar(status_short)

    date_str = fixture.get("date")
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        time_local = dt.strftime("%H:%M")
        day_local = dt.strftime("%Y-%m-%d")
    except Exception:
        time_local = "غير معروف"
        day_local = "غير معروف"

    lines = []
    lines.append(f"🏆 <b>{league.get('name','بطولة غير معروفة')}</b>")
    lines.append(f"⚽ <b>{home}</b> × <b>{away}</b>")
    lines.append(f"⏳ <b>الموعد:</b> {day_local} — {time_local}")
    if hg is not None and ag is not None:
        lines.append(f"🔢 <b>النتيجة:</b> {hg} - {ag}")
    lines.append(f"⌛ <b>الحالة:</b> {status_ar}")
    if league.get("country"):
        lines.append(f"🌍 <b>الدولة:</b> {league['country']}")
    return "\n".join(lines)

def send_fixture_message(title, fix, extra_note):
    body = format_fixture_lines(fix)
    text = f"🔴 <b>{title}</b>\n\n{body}\n\n📝 {extra_note}{FOOTER}"
    send_text_to_channel(text)

def process_fixtures():
    global sent_fixture_schedules, sent_fixture_results, last_fixture_state, current_day

    # reset يوم جديد
    today = date.today()
    if today != current_day:
        current_day = today
        sent_fixture_schedules = set()
        sent_fixture_results = set()
        last_fixture_state = {}
        print("📅 يوم جديد، تم إعادة ضبط حالة المباريات.")

    day_str = datetime.utcnow().strftime("%Y-%m-%d")
    data = api_get("/fixtures", {"date": day_str, "timezone": "Asia/Jerusalem"})
    if not data or "response" not in data:
        print("⚠️ لا توجد مباريات اليوم أو فشل الجلب.")
        return

    fixtures = data["response"]
    live_codes = {"1H", "2H", "ET", "P", "LIVE"}

    for fix in fixtures:
        fixture = fix.get("fixture", {})
        fid = fixture.get("id")
        if not fid:
            continue

        status_obj = fixture.get("status", {})
        status_short = status_obj.get("short", "")

        goals = fix.get("goals", {})
        hg = goals.get("home")
        ag = goals.get("away")

        prev = last_fixture_state.get(fid)
        curr = (status_short, hg, ag)
        last_fixture_state[fid] = curr

        # مباريات قادمة (موعد فقط)
        if status_short in ("NS", "TBD", "") and fid not in sent_fixture_schedules:
            send_fixture_message(
                "مباراة اليوم",
                fix,
                "إعلان عن موعد مباراة ضمن جدول اليوم."
            )
            sent_fixture_schedules.add(fid)
            time.sleep(1)
            continue

        # نهاية المباراة
        if status_short in ("FT", "AET", "PEN") and fid not in sent_fixture_results:
            send_fixture_message(
                "نتيجة نهائية لمباراة اليوم",
                fix,
                "انتهت المباراة وتم تحديث النتيجة النهائية."
            )
            sent_fixture_results.add(fid)
            time.sleep(1)
            continue

        # تحديث مباشر (هدف / تغيير في النتيجة)
        if prev is not None and curr != prev and status_short in live_codes:
            send_fixture_message(
                "تحديث مباشر (تغيير في النتيجة)",
                fix,
                "قد يكون هذا التحديث بسبب هدف جديد أو تغيير في مجريات المباراة."
            )
            time.sleep(1)

# ============================
#   الحلقة الرئيسية
# ============================

def run_bot():
    print("🚀 F90 Sports Bot يعمل الآن…")
    send_text_to_channel("⚽ <b>بوت F90 Sports تم تشغيله بنجاح ويعمل الآن تلقائياً.</b>")
    while True:
        try:
            process_sports_rss()
            process_fixtures()
        except Exception as e:
            print("⚠️ خطأ في الحلقة الرئيسية:", e)
        print("⏸️ انتظار 60 ثانية قبل التحديث التالي…")
        time.sleep(60)

# ============================
#   Flask لـ Render
# ============================

app = Flask(__name__)

@app.route("/")
def home():
    return "✅ F90 Sports Bot يعمل الآن 24/7."

@app.route("/test")
def test():
    test_msg = (
        "⚽ <b>رسالة اختبار من F90 Sports Bot</b>\n\n"
        "إذا وصلتك هذه الرسالة في قناة F90Sports فالبوت يعمل بنجاح ✅"
        f"{FOOTER}"
    )
    send_text_to_channel(test_msg)
    return "تم إرسال رسالة اختبار إلى القناة."

def run_flask():
    app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_bot()
