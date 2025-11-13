import feedparser
import requests
import time
import re
from html import unescape
import os
import threading
from flask import Flask

BOT_TOKEN = os.getenv("BOT_TOKEN", "8340084044:AAH4xDclN0yKECmpTFcnL5eshA4-qREHw4w")
CHAT_ID = os.getenv("CHAT_ID", "@f90newsnow")

SOURCES = [
    "https://www.aljazeera.net/xml/rss/all.xml",
    "https://www.skynewsarabia.com/web/rss",
    "https://arabic.rt.com/rss/",
    "https://www.alarabiya.net/.mrss/ar.xml",
    "https://www.bbc.com/arabic/index.xml",
    "https://www.asharqnews.com/ar/rss.xml",
    "https://shehabnews.com/ar/rss.xml",
    "https://qudsn.co/feed",
    "https://maannews.net/rss/ar.xml"
]

FOOTER = (
    "\n\n———\n"
    "📢 انضموا لنا لتَروا الأخبار لحظة بلحظة\n"
    "🌐 <a href='https://e9dd-009-80041-a80rjkupq6lz-deployed-internal.easysite.ai/'>موقعنا الرسمي</a>\n"
    "📲 <a href='https://newoaks.s3.us-west-1.amazonaws.com/AutoDev/80041/d281064b-a82e-4fdf-bc19-d19cc4e0ccd4.apk'>تحميل تطبيق الأندرويد</a>\n"
    "📡 <a href='https://t.me/f90newsnow'>تابعنا على تلجرام</a>"
)

seen = set()

def clean_text(s):
    s = unescape(s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def get_image(entry):
    for key in ("media_content", "media_thumbnail", "enclosures"):
        if key in entry:
            try:
                data = entry[key][0] if isinstance(entry[key], list) else entry[key]
                url = data.get("url") or data.get("href")
                if url and url.startswith("http"):
                    return url
            except Exception:
                pass

    if "summary" in entry:
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', entry["summary"])
        if m:
            return m.group(1)
    return None

def send_message(title, source, link, img=None):
    caption = (
        f"🔴 <b>{clean_text(title)}</b>\n"
        f"📰 <i>{source}</i>\n"
        f"<a href='{link}'>🔗 رابط الخبر</a>"
        f"{FOOTER}"
    )

    if img:
        try:
            photo_data = requests.get(img, timeout=10).content
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": photo_data}
            )
        except:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={"chat_id": CHAT_ID, "text": caption, "parse_mode": "HTML"}
            )
    else:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": caption, "parse_mode": "HTML"}
        )

def run_bot():
    print("🚀 F90 News Bot يعمل الآن…")
    while True:
        new_count = 0
        for url in SOURCES:
            try:
                feed = feedparser.parse(url)
                source = feed.feed.get("title", "خبر عاجل")
                for entry in reversed(feed.entries):
                    link = entry.get("link")
                    if not link or link in seen:
                        continue
                    seen.add(link)
                    title = entry.get("title", "")
                    img = get_image(entry)
                    send_message(title, source, link, img)
                    new_count += 1
                    time.sleep(2)
            except Exception as e:
                print("⚠️ خطأ:", e)

        if new_count == 0:
            print("⏸️ لا أخبار جديدة… الانتظار 60 ثانية")
        time.sleep(60)

app = Flask(__name__)

@app.route("/")
def home():
    return "✅ F90 News Bot يعمل الآن 24/7 دون توقف!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    run_bot()
