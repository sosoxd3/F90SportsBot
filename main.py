import os
import time
import threading
import re
from datetime import datetime, timedelta

import feedparser
import requests
from html import unescape
from flask import Flask
from deep_translator import GoogleTranslator
import json

# ============================
# إعدادات عامة
# ============================

BOT_TOKEN = os.getenv("BOT_TOKEN", "8278742496:AAH8lDMB0ci6mX0I7JIiIbuB8ZudyWVqT3E")
CHAT_ID = os.getenv("CHAT_ID", "@F90Sports")
API_FOOTBALL_KEY = os.getenv(
    "API_FOOTBALL_KEY",
    "3caa9eece931b202667d7c0e71ebe84918e5ac75adc7669ea0522ef241326e6f",
)

# لوجو القناة الرياضي (صورة افتراضية إذا ما في صورة للخبر)
DEFAULT_IMAGE_URL = "https://i.ibb.co/KzQK444K/file-00000000581871f5944b3ab066a737a1.png"

# مصادر أخبار كرة القدم (RSS)
SPORTS_SOURCES = [
    # عربية
    "https://www.kooora.com/rss.aspx?region=-1",  # كووورة (عام)
    "https://www.yallakora.com/feed",            # يلا كورة
    # عالمية (إنجليزية – سيتم ترجمتها قدر الإمكان)
    "https://www.espn.com/espn/rss/soccer/news",
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.skysports.com/feeds/rss/12040",  # كرة قدم
    # كينغز ليغ (نستخدم مصدر قريب عن الليجا)
    "https://www.marca.com/en/rss/futbol.html",
]

# إعدادات مظهر الرسالة
FOOTER = (
    "\n\n——————————\n"
    "📢 تابعوا أحدث الأخبار الرياضية لحظة بلحظة\n"
    "⚽ قناة الرياضة: @F90Sports\n"
    "📡 قناة الأخبار: @F90NewsNow\n"
)

seen_links = set()
seen_titles = set()
SEEN_LIMIT = 5000

# لتتبع تحديثات المباريات
FIXTURES_CACHE = {}  # fixture_id -> {"status": str, "goals": (home, away)}

# ============================
# دوال مساعدة عامة
# ============================


def clean_html(raw: str) -> str:
    if not raw:
        return ""
    raw = unescape(raw)
    raw = re.sub(r"<[^>]+>", " ", raw)  # إزالة وسوم HTML
    raw = re.sub(r"http\S+", "", raw)   # إزالة الروابط
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def looks_like_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def translate_to_ar(text: str) -> str:
    """ترجمة النص للعربية قدر الإمكان، ولو فشلت يرجع النص الأصلي."""
    if not text:
        return text
    if looks_like_arabic(text):
        return text
    try:
        return GoogleTranslator(source="auto", target="ar").translate(text)
    except Exception as e:
        print("⚠️ فشل الترجمة:", e)
        return text


def get_entry_datetime(entry):
    for key in ("published_parsed", "updated_parsed"):
        if key in entry and entry[key]:
            try:
                tt = entry[key]
                return datetime(*tt[:6])
            except Exception:
                continue
    return None


def is_recent(entry, hours=24):
    dt = get_entry_datetime(entry)
    if not dt:
        return False
    return (datetime.utcnow() - dt) <= timedelta(hours=hours)


def shrink_seen_sets():
    global seen_links, seen_titles
    if len(seen_links) > SEEN_LIMIT:
        seen_links = set(list(seen_links)[-SEEN_LIMIT // 2:])
    if len(seen_titles) > SEEN_LIMIT:
        seen_titles = set(list(seen_titles)[-SEEN_LIMIT // 2:])


def get_image(entry):
    for key in ("media_content", "media_thumbnail", "enclosures"):
        if key in entry:
            try:
                data = entry[key][0] if isinstance(entry[key], list) else entry[key]
                url = data.get("url") or data.get("href")
                if url and url.startswith("http") and not url.lower().endswith(".mp4"):
                    return url
            except Exception:
                pass
    summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
    if m:
        return m.group(1)
    return DEFAULT_IMAGE_URL


def get_full_text(entry) -> str:
    if "summary" in entry:
        return clean_html(entry.summary)
    if "description" in entry:
        return clean_html(entry.description)
    return ""


# ============================
# إرسال الرسائل إلى تيليجرام
# ============================


def send_photo_or_text(caption: str, image_url: str | None = None, reply_markup=None):
    if image_url:
        try:
            img_data = requests.get(image_url, timeout=15).content
            data = {
                "chat_id": CHAT_ID,
                "caption": caption,
                "parse_mode": "HTML",
            }
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup)
            resp = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data=data,
                files={"photo": img_data},
                timeout=30,
            )
            if resp.status_code != 200:
                print("⚠️ خطأ إرسال صورة:", resp.text)
                raise RuntimeError("photo error")
            return
        except Exception as e:
            print("⚠️ فشل إرسال الصورة، سيتم الإرسال كنص فقط:", e)

    # fallback نص فقط
    data = {
        "chat_id": CHAT_ID,
        "text": caption,
        "parse_mode": "HTML",
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=data,
        timeout=30,
    )
    if resp.status_code != 200:
        print("⚠️ خطأ إرسال رسالة نصية:", resp.text)


def send_sports_news(title_ar, summary_ar, details_ar, link=None, image_url=None):
    # ملخص + تفاصيل كاملة + بدون سطر "المصدر"
    caption = f"⚽️ <b>{title_ar}</b>\n\n"
    if summary_ar:
        caption += f"📌 <b>ملخص قصير:</b>\n{summary_ar}\n\n"
    caption += f"📄 <b>التفاصيل الكاملة:</b>\n{details_ar}\n"
    caption += FOOTER

    # أزرار مخفية للروابط
    buttons = []
    if link:
        buttons.append([{"text": "🌍 قراءة الخبر من الموقع", "url": link}])
    buttons.append([{"text": "📡 قناة F90 Sports", "url": "https://t.me/F90Sports"}])

    reply_markup = {"inline_keyboard": buttons}

    send_photo_or_text(caption, image_url=image_url, reply_markup=reply_markup)


# ============================
# أخبار الرياضة من RSS
# ============================


def process_sports_feeds():
    global seen_links, seen_titles
    new_count = 0

    for url in SPORTS_SOURCES:
        try:
            feed = feedparser.parse(url)
            # source = feed.feed.get("title", "مصدر رياضي")  # لم نعد نعرضه نصياً

            for entry in reversed(feed.entries):
                if not is_recent(entry, hours=24):
                    continue

                link = entry.get("link", "")
                if not link:
                    continue

                title_raw = entry.get("title", "خبر رياضي")
                title_clean = clean_html(title_raw)
                if not title_clean:
                    continue

                key_title = title_clean.lower()
                if link in seen_links or key_title in seen_titles:
                    continue

                raw_text = get_full_text(entry)
                if len(raw_text) < 30:
                    continue

                # ترجمة
                title_ar = translate_to_ar(title_clean)

                details_ar = translate_to_ar(raw_text)
                if len(details_ar) > 2000:
                    details_ar = details_ar[:2000] + "..."

                summary_ar = details_ar[:260]  # ملخص قصير

                image_url = get_image(entry)

                send_sports_news(title_ar, summary_ar, details_ar, link=link, image_url=image_url)

                seen_links.add(link)
                seen_titles.add(key_title)
                new_count += 1

                time.sleep(2)

        except Exception as e:
            print("⚠️ خطأ في المصدر الرياضي:", url, e)

    return new_count


# ============================
# مواعيد مباريات اليوم (API-FOOTBALL) مع تحديث مستمر
# ============================

IMPORTANT_LEAGUES = [
    39,   # Premier League
    140,  # La Liga
    135,  # Serie A
    78,   # Bundesliga
    61,   # Ligue 1
    2,    # Champions League
]


def fetch_today_fixtures_state():
    """جلب حالة مباريات اليوم (للدوريات المهمة) مع تفاصيل أساسية."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    headers = {"x-apisports-key": API_FOOTBALL_KEY}

    fixtures = []

    for league_id in IMPORTANT_LEAGUES:
        try:
            params = {
                "date": today,
                "league": league_id,
                "timezone": "Asia/Jerusalem",
            }
            resp = requests.get(
                "https://v3.football.api-sports.io/fixtures",
                headers=headers,
                params=params,
                timeout=20,
            )
            data = resp.json()
            for item in data.get("response", []):
                fixture = item.get("fixture", {})
                league = item.get("league", {})
                teams = item.get("teams", {})
                goals = item.get("goals", {})

                fixture_id = fixture.get("id")
                if fixture_id is None:
                    continue

                league_name = league.get("name", "دوري")
                home_name = teams.get("home", {}).get("name", "الفريق 1")
                away_name = teams.get("away", {}).get("name", "الفريق 2")

                status = fixture.get("status", {}).get("short", "")
                date_iso = fixture.get("date")
                time_str = ""
                if date_iso:
                    try:
                        dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
                        dt_local = dt + timedelta(hours=2)  # تقريباً توقيت القدس
                        time_str = dt_local.strftime("%H:%M")
                    except Exception:
                        pass

                home_g = goals.get("home")
                away_g = goals.get("away")

                fixtures.append(
                    {
                        "id": fixture_id,
                        "league": league_name,
                        "home": home_name,
                        "away": away_name,
                        "time": time_str,
                        "status": status,
                        "home_g": home_g,
                        "away_g": away_g,
                    }
                )
        except Exception as e:
            print("⚠️ خطأ في جلب مباريات الدوري", league_id, e)

    return fixtures


def format_fixture_message(fx, kind="update"):
    league = fx["league"]
    home = fx["home"]
    away = fx["away"]
    time_str = fx["time"]
    status = fx["status"]
    hg = fx["home_g"]
    ag = fx["away_g"]

    if kind == "scheduled":
        title = "📅 مباراة قادمة اليوم"
    elif kind == "finished":
        title = "✅ نهاية المباراة"
    else:
        title = "🔥 تحديث مباشر للمباراة"

    msg = f"{title}\n\n"
    msg += f"🏆 {league}\n"
    msg += f"⚔ {home} vs {away}\n"
    if time_str:
        msg += f"⏰ التوقيت (تقريباً): {time_str} – بتوقيت القدس\n"
    if hg is not None and ag is not None:
        msg += f"🔢 النتيجة الحالية: {hg} : {ag}\n"
    msg += "\n📺 ابحث عن البث المباشر حسب قنوات بلدك أو منصات البث.\n"
    msg += FOOTER
    return msg


def check_fixture_updates():
    """تحديث مستمر: إذا تغيرت نتيجة أو حالة مباراة → ينشر منشور."""
    global FIXTURES_CACHE
    fixtures = fetch_today_fixtures_state()
    if not fixtures:
        return

    for fx in fixtures:
        fid = fx["id"]
        status = fx["status"]
        goals = (fx["home_g"], fx["away_g"])

        prev = FIXTURES_CACHE.get(fid)
        if prev is None:
            # أول مرة نشوف هذه المباراة → نرسل إشعار عن مباراة قادمة
            if status in ("NS", "TBD"):
                msg = format_fixture_message(fx, kind="scheduled")
                send_photo_or_text(msg)
            FIXTURES_CACHE[fid] = {"status": status, "goals": goals}
            continue

        # تغيير في الحالة أو النتيجة
        if status != prev["status"] or goals != prev["goals"]:
            kind = "finished" if status == "FT" else "update"
            msg = format_fixture_message(fx, kind=kind)
            send_photo_or_text(msg)
            FIXTURES_CACHE[fid] = {"status": status, "goals": goals}


# ============================
# حلقة تشغيل البوت
# ============================


def run_bot():
    print("🚀 F90 Sports Bot يعمل الآن…")
    while True:
        shrink_seen_sets()

        # 1) أخبار الرياضة (RSS + ترجمة + صور + أزرار)
        new_news = process_sports_feeds()
        if new_news == 0:
            print("⏸ لا أخبار رياضية جديدة الآن.")

        # 2) تحديثات المباريات (كل تغيير بالنتيجة/الحالة)
        check_fixture_updates()

        time.sleep(60)  # انتظر 60 ثانية ثم أعد الدورة


# ============================
# Flask ليبقى البوت حي على Render
# ============================

app = Flask(__name__)


@app.route("/")
def home():
    return "✅ F90 Sports Bot يعمل الآن 24/7."


@app.route("/test")
def test():
    msg = (
        "🏟 <b>رسالة اختبار من F90 Sports Bot</b>\n\n"
        "إذا وصلتك هذه الرسالة في القناة، فالبوت الرياضي يعمل بنجاح ✅"
        f"{FOOTER}"
    )
    send_photo_or_text(msg)
    return "تم إرسال رسالة اختبار إلى القناة."


def run_flask():
    app.run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    run_bot()
