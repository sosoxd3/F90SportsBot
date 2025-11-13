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

# ============================
# إعدادات عامة
# ============================

BOT_TOKEN = os.getenv("BOT_TOKEN", "8278742496:AAH8lDMB0ci6mX0I7JIiIbuB8ZudyWVqT3E")
CHAT_ID = os.getenv("CHAT_ID", "@F90Sports")
API_FOOTBALL_KEY = os.getenv(
    "API_FOOTBALL_KEY",
    "3caa9eece931b202667d7c0e71ebe84918e5ac75adc7669ea0522ef241326e6f",
)

DIRECT_LINK = "https://www.effectivegatecpm.com/y7ytegiy?key=8987b0a0eccadab53fa69732c3e254b8"

DEFAULT_IMAGE_URL = None

SPORTS_SOURCES = [
    "https://www.kooora.com/rss.aspx?region=-1",
    "https://www.yallakora.com/feed",
    "https://www.espn.com/espn/rss/soccer/news",
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.skysports.com/feeds/rss/12040",
    "https://www.marca.com/en/rss/futbol.html",
]

FOOTER = (
    "\n\n——————————\n"
    "📢 تابعوا أحدث الأخبار الرياضية لحظة بلحظة\n"
    "📡 قناة الرياضة: @F90Sports\n"
    "📡 قناة الرياضة: @F90newsnow\n"
    "\n🎥 <b>بث مباشر مباريات اليوم:</b>\n"
    f"🔗 <a href=\"{DIRECT_LINK}\">اضغط هنا</a>\n"
)

seen_links = set()
seen_titles = set()
SEEN_LIMIT = 5000
last_matches_day = None  # مباريات اليوم


# ============================
# دوال مساعدة
# ============================

def clean_html(raw: str) -> str:
    if not raw:
        return ""
    raw = unescape(raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"http\S+", "", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def looks_like_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text))


def translate_to_ar(text: str) -> str:
    if not text:
        return text
    if looks_like_arabic(text):
        return text
    try:
        return GoogleTranslator(source="auto", target="ar").translate(text)
    except:
        return text


def get_entry_datetime(entry):
    for key in ("published_parsed", "updated_parsed"):
        if key in entry and entry[key]:
            try:
                tt = entry[key]
                return datetime(*tt[:6])
            except:
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
        seen_links = set(list(seen_links)[-2500:])
    if len(seen_titles) > SEEN_LIMIT:
        seen_titles = set(list(seen_titles)[-2500:])


def get_image(entry):
    for key in ("media_content", "media_thumbnail", "enclosures"):
        if key in entry:
            try:
                data = entry[key][0] if isinstance(entry[key], list) else entry[key]
                url = data.get("url") or data.get("href")
                if url and not url.endswith(".mp4"):
                    return url
            except:
                pass
    summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
    if m:
        return m.group(1)
    return DEFAULT_IMAGE_URL


def get_full_text(entry):
    if "summary" in entry:
        return clean_html(entry.summary)
    if "description" in entry:
        return clean_html(entry.description)
    return ""


# ============================
# إرسال الرسالة
# ============================

def send_photo_or_text(caption, image_url=None):
    if image_url:
        try:
            img_data = requests.get(image_url, timeout=15).content
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": img_data},
                timeout=25,
            )
            if r.status_code == 200:
                return
        except:
            pass

    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": caption, "parse_mode": "HTML"},
    )


def send_sports_news(title, source, details, image_url=None):
    caption = (
        f"⚽️ <b>{title}</b>\n\n"
        f"📄 <b>التفاصيل:</b>\n{details}\n\n"
        f"📰 <i>{source}</i>"
        f"{FOOTER}"
    )
    send_photo_or_text(caption, image_url)


# ============================
# أخبار RSS
# ============================

def process_sports_feeds():
    new_count = 0
    for url in SPORTS_SOURCES:
        try:
            feed = feedparser.parse(url)
            source = feed.feed.get("title", "مصدر رياضي")

            for entry in reversed(feed.entries):
                if not is_recent(entry):
                    continue

                link = entry.get("link", "")
                title = clean_html(entry.get("title", ""))

                if not title or link in seen_links:
                    continue

                details = get_full_text(entry)
                if len(details) < 20:
                    continue

                title_ar = translate_to_ar(title)
                details_ar = translate_to_ar(details)
                image = get_image(entry)

                send_sports_news(title_ar, source, details_ar, image)

                seen_links.add(link)
                seen_titles.add(title.lower())
                new_count += 1
                time.sleep(2)

        except Exception as e:
            print("⚠️ خطأ:", e)

    return new_count


# ============================
# مباريات اليوم
# ============================

IMPORTANT_LEAGUES = [39, 140, 135, 78, 61, 2]


def fetch_matches():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    matches = []

    for league in IMPORTANT_LEAGUES:
        try:
            r = requests.get(
                "https://v3.football.api-sports.io/fixtures",
                params={"date": today, "league": league, "timezone": "Asia/Jerusalem"},
                headers=headers, timeout=20,
            )
            data = r.json()
            matches.extend(data.get("response", []))
        except:
            continue

    return matches


def send_today_matches():
    global last_matches_day
    today = datetime.utcnow().strftime("%Y-%m-%d")

    if last_matches_day == today:
        return

    matches = fetch_matches()
    if not matches:
        return

    msg = ["🏟 <b>مباريات اليوم (توقيت القدس)</b>\n"]

    for m in matches:
        league = m["league"]["name"]
        home = m["teams"]["home"]["name"]
        away = m["teams"]["away"]["name"]
        time_str = m["fixture"]["date"][11:16]

        msg.append(f"🏆 {league}\n• {home} vs {away} — {time_str}\n")

    msg.append("📺 قد تختلف القنوات الناقلة حسب بلدك.")
    send_photo_or_text("\n".join(msg))

    last_matches_day = today


# ============================
# حلقة البوت
# ============================

def run_bot():
    print("🚀 F90 Sports Bot يعمل...")
    while True:
        shrink_seen_sets()

        process_sports_feeds()
        send_today_matches()

        time.sleep(60)


# ============================
# Flask للحفاظ على البوت حي
# ============================

app = Flask(__name__)

@app.route("/")
def home():
    return "F90 Sports Bot يعمل الآن 24/7 ✔"

@app.route("/test")
def test():
    send_photo_or_text("رسالة اختبار — البوت يعمل 👍")
    return "Test sent"

def run_flask():
    app.run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    run_bot()
