import feedparser
import requests
import time
import re
import os
import threading
from datetime import datetime, timedelta
from html import unescape
from flask import Flask

# ============================
#   إعدادات البوت
# ============================

# توكن بوت الرياضة
BOT_TOKEN = os.getenv("BOT_TOKEN", "8349529503:AAGj-SNuDNuhxmb22J13L9fkH_9DE1FFlIg")
# قناة الرياضة
CHAT_ID = os.getenv("CHAT_ID", "@F90Sports")

# مفتاح API-FOOTBALL (استخدمنا المفتاح الذي أعطيتني إياه)
API_FOOTBALL_KEY = os.getenv(
    "API_FOOTBALL_KEY",
    "3caa9eece931b202667d7c0e71ebe84918e5ac75adc7669ea0522ef241326e6f"
)

# لوغو القناة في حال ما في صورة للخبر
LOGO_URL = "https://i.ibb.co/KzQK444K/file-00000000581871f5944b3ab066a737a1.png"

# مصادر أخبار كرة القدم (RSS)
SOURCES = [
    # عربي
    "https://www.kooora.com/xml/rss.aspx?cup=0&region=-1&team=0&tour=0",
    "https://www.yallakora.com/rss/288",
    # إنجليزي
    "https://www.bbc.com/sport/football/rss.xml",
    "https://www.espn.com/espn/rss/soccer/news",
    "https://www.skysports.com/rss/12040",
    "https://www.goal.com/feeds/en/news",
    # كينغز ليغ – غالباً ووردبريس
    "https://kingsleague.pro/feed/",
]

FOOTER = (
    "📢 انضموا لقناة الرياضة الأقوى F90 Sports\n"
    "⚽ نتائج، أخبار، انتقالات، مواعيد المباريات وأكثر…\n"
    "📡 التلجرام: https://t.me/F90Sports"
)

# مجموعات التكرار
seen_links = set()
seen_titles = set()
SEEN_LIMIT = 5000

# توقيت آخر منشور مباريات اليوم
last_fixtures_time = 0  # مرة كل ساعة كحد أقصى

# ============================
#   دوال مساعدة
# ============================


def clean_html(raw: str) -> str:
    if not raw:
        return ""
    raw = unescape(raw)
    raw = re.sub(r"<[^>]+>", " ", raw)      # إزالة HTML
    raw = re.sub(r"http\S+", "", raw)       # إزالة أي روابط
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def is_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def translate_to_arabic(text: str) -> str:
    """ترجمة نص غير عربي إلى العربية (إذا كان قصيراً أو متوسطاً)."""
    if not text:
        return ""
    if is_arabic(text):
        return text
    try:
        # استخدام ترجمة جوجل البسيطة عبر واجهة مفتوحة
        # (بدون مكتبة إضافية حتى لا يحصل مشاكل تنصيب)
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": "ar",
            "dt": "t",
            "q": text,
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        translated = "".join(part[0] for part in data[0])
        return translated
    except Exception:
        # إذا الترجمة فشلت نرجع النص الأصلي
        return text


def get_full_text(entry) -> str:
    for key in ("summary", "description", "content"):
        if hasattr(entry, key):
            return clean_html(getattr(entry, key))
        if key in entry:
            return clean_html(entry[key])
    return ""


def get_image(entry):
    # نحاول جلب صورة من RSS
    for key in ("media_content", "media_thumbnail", "enclosures"):
        if key in entry:
            try:
                data = entry[key][0] if isinstance(entry[key], list) else entry[key]
                url = data.get("url") or data.get("href")
                if url and url.startswith("http") and not url.endswith(".mp4"):
                    return url
            except Exception:
                pass

    summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
    if m:
        return m.group(1)

    # fallback: لوغو القناة
    return LOGO_URL


def get_video(entry):
    for key in ("media_content", "enclosures"):
        if key in entry:
            items = entry[key] if isinstance(entry[key], list) else [entry[key]]
            for it in items:
                url = it.get("url") or it.get("href")
                if url and url.startswith("http") and url.endswith(".mp4"):
                    return url

    summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
    links = re.findall(r"(https?://\S+)", summary)
    for l in links:
        if l.endswith(".mp4"):
            return l

    return None


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


# ============================
#   إرسال الأخبار
# ============================


def send_news(title, source, details, img=None, video=None, original_snippet=None):
    title_ar = translate_to_arabic(title)
    details = details.strip()
    if len(details) > 2000:
        details = details[:2000] + "..."

    details_ar = translate_to_arabic(details)

    if original_snippet and len(original_snippet) > 400:
        original_snippet = original_snippet[:400] + "..."

    caption = (
        f"🔴 <b>{title_ar}</b>\n\n"
        f"📄 <b>التفاصيل:</b>\n{details_ar}\n\n"
        f"📰 <b>المصدر:</b> {source}"
    )

    if original_snippet and not is_arabic(original_snippet):
        caption += f"\n\n🌍 <b>مقتطف من النص الأصلي:</b>\n{original_snippet}"

    caption += FOOTER

    # فيديو أولاً إن وجد
    if video:
        try:
            vdata = requests.get(video, timeout=15).content
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo",
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"video": vdata},
                timeout=20,
            )
            return
        except Exception as e:
            print("⚠️ فشل إرسال الفيديو:", e)

    # صورة
    if img:
        try:
            pdata = requests.get(img, timeout=10).content
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": pdata},
                timeout=20,
            )
            return
        except Exception as e:
            print("⚠️ فشل إرسال الصورة:", e)

    # نص فقط
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": caption, "parse_mode": "HTML"},
            timeout=20,
        )
    except Exception as e:
        print("⚠️ فشل إرسال الرسالة النصية:", e)


# ============================
#   مباريات اليوم – API-FOOTBALL
# ============================


def fetch_fixtures():
    """جلب مباريات اليوم من API-FOOTBALL (أهم الدوريات)."""
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        url = f"https://v3.football.api-sports.io/fixtures?date={today}&timezone=Asia/Jerusalem"
        headers = {"x-apisports-key": API_FOOTBALL_KEY}
        res = requests.get(url, headers=headers, timeout=15)
        data = res.json()

        fixtures = data.get("response", [])
        if not fixtures:
            return None

        # نهتم فقط بالدوريات الكبيرة + كينغز ليغ إن وجدت
        important_leagues = {
            "UEFA Champions League",
            "Premier League",
            "La Liga",
            "Serie A",
            "Bundesliga",
            "Ligue 1",
            "Saudi Professional League",
            "Kings League",
        }

        lines = []
        for fx in fixtures:
            league = fx["league"]["name"]
            if league not in important_leagues:
                continue

            home = fx["teams"]["home"]["name"]
            away = fx["teams"]["away"]["name"]
            status = fx["fixture"]["status"]["short"]
            t = fx["fixture"]["date"]  # ISO

            # توقيت مبسط HH:MM
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M")

            goals_home = fx["goals"]["home"]
            goals_away = fx["goals"]["away"]

            if status in ("NS", "TBD"):
                score = "لم تبدأ بعد"
            elif goals_home is None or goals_away is None:
                score = "جارٍ اللعب"
            else:
                score = f"{goals_home} : {goals_away}"

            yt_query = f"{home} vs {away} live"
            yt_link = f"https://www.youtube.com/results?search_query={yt_query.replace(' ', '+')}"

            line = (
                f"🏟 {league}\n"
                f"⚔ {home} vs {away}\n"
                f"⏰ {time_str} | 🔢 النتيجة: {score}\n"
                f"🔗 بث (بحث يوتيوب): {yt_link}\n"
                "———"
            )
            lines.append(line)

        if not lines:
            return None

        text = "📆 <b>مباريات اليوم – أهم الدوريات</b>\n\n" + "\n".join(lines)
        return text
    except Exception as e:
        print("⚠️ خطأ في جلب المباريات:", e)
        return None


def send_fixtures_if_needed():
    global last_fixtures_time
    now = time.time()
    # مرة كل ساعة كحد أقصى
    if now - last_fixtures_time < 3600:
        return

    fx_text = fetch_fixtures()
    if not fx_text:
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": fx_text, "parse_mode": "HTML"},
            timeout=20,
        )
        last_fixtures_time = now
        print("📊 تم إرسال منشور مباريات اليوم.")
    except Exception as e:
        print("⚠️ فشل إرسال منشور المباريات:", e)


# ============================
#   حلقة تشغيل الأخبار
# ============================


def run_bot():
    print("🚀 F90 Sports Bot يعمل الآن…")
    while True:
        shrink_seen_sets()
        send_fixtures_if_needed()
        new_count = 0

        for url in SOURCES:
            try:
                feed = feedparser.parse(url)
                source = feed.feed.get("title", "مصدر رياضي")

                for entry in reversed(feed.entries):
                    if not is_recent(entry, hours=24):
                        continue

                    link = entry.get("link", "")
                    if not link:
                        continue

                    title = clean_html(entry.get("title", "خبر رياضي عاجل"))
                    if not title:
                        continue

                    key_title = title.lower()
                    if link in seen_links or key_title in seen_titles:
                        continue

                    details = get_full_text(entry)
                    if len(details) < 30:
                        continue

                    img = get_image(entry)
                    vid = get_video(entry)

                    snippet = details[:300]

                    send_news(title, source, details, img, vid, original_snippet=snippet)

                    seen_links.add(link)
                    seen_titles.add(key_title)
                    new_count += 1

                    time.sleep(2)

            except Exception as e:
                print("⚠️ خطأ في المصدر:", url, e)

        if new_count == 0:
            print("⏸️ لا أخبار رياضية جديدة الآن، انتظار 60 ثانية…")

        time.sleep(60)


# ============================
#   Flask ليبقى البوت حي على Render
# ============================

app = Flask(__name__)


@app.route("/")
def home():
    return "✅ F90 Sports Bot يعمل الآن 24/7 – أخبار + نتائج + مواعيد."


@app.route("/test")
def test():
    test_msg = (
        "⚽ <b>منشور تجريبي من F90 Sports Bot</b>\n\n"
        "إذا وصلتك هذه الرسالة في قناة الرياضة، فالبوت يعمل بنجاح ✅\n"
        f"{FOOTER}"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": test_msg, "parse_mode": "HTML"},
            timeout=20,
        )
    except Exception as e:
        return f"حدث خطأ أثناء إرسال رسالة الاختبار: {e}"
    return "تم إرسال رسالة اختبار إلى القناة."


def run_flask():
    app.run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    run_bot()
