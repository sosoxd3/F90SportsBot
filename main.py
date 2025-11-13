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

# لوجو القناة الرياضي (استعمل رابط صورة القناة من تيليجرام أو أي استضافة لاحقًا إن حبيت)
DEFAULT_IMAGE_URL = None  # لو حاب تضيف رابط ثابت للصورة، ضعه هنا كنص


# مصادر أخبار كرة القدم (RSS)
SPORTS_SOURCES = [
    # عربية
    "https://www.kooora.com/rss.aspx?region=-1",  # كووورة (عام)
    "https://www.yallakora.com/feed",            # يلا كورة
    # عالمية (إنجليزية – سيتم ترجمتها قدر الإمكان)
    "https://www.espn.com/espn/rss/soccer/news",
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.skysports.com/feeds/rss/12040",  # كرة قدم
    # كينغز ليغ (مافي RSS رسمي، نستخدم أخبار عامة عن الدوري الإسباني كمصدر قريب)
    "https://www.marca.com/en/rss/futbol.html",
]

# إعدادات مظهر الرسالة
FOOTER = (
    "\n\n——————————\n"
    "📢 تابعوا أحدث الأخبار الرياضية لحظة بلحظة\n"
    "📡 قناة الرياضة: @F90Sports\n"
)

seen_links = set()
seen_titles = set()
SEEN_LIMIT = 5000

last_matches_day = None  # لعدم تكرار نشر مباريات اليوم أكثر من مرة باليوم

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
    return bool(re.search(r"[\u0600-\u06FF]", text))


def translate_to_ar(text: str) -> str:
    """ترجمة النص للعربية قدر الإمكان، ولو فشلت يرجع النص الأصلي."""
    if not text:
        return text
    # لو النص أصلاً عربي، رجّعه كما هو
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
                if url and url.startswith("http"):
                    # نتجنب فيديوهات mp4 هنا
                    if not url.lower().endswith(".mp4"):
                        return url
            except Exception:
                pass
    # محاولة استخراج صورة من الملخص
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


def send_photo_or_text(caption: str, image_url: str | None = None):
    if image_url:
        try:
            img_data = requests.get(image_url, timeout=15).content
            resp = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
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
    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": caption, "parse_mode": "HTML"},
        timeout=30,
    )
    if resp.status_code != 200:
        print("⚠️ خطأ إرسال رسالة نصية:", resp.text)


def send_sports_news(title, source, details, image_url=None):
    caption = (
        f"⚽️ <b>{title}</b>\n\n"
        f"📄 <b>التفاصيل:</b>\n{details}\n\n"
        f"📰 <i>{source}</i>"
        f"{FOOTER}"
    )
    send_photo_or_text(caption, image_url)


# ============================
# أخبار الرياضة من RSS
# ============================


def process_sports_feeds():
    global seen_links, seen_titles
    new_count = 0

    for url in SPORTS_SOURCES:
        try:
            feed = feedparser.parse(url)
            source = feed.feed.get("title", "مصدر رياضي")

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

                # نص الخبر
                raw_text = get_full_text(entry)
                if len(raw_text) < 30:
                    continue

                # ترجمة
                title_ar = translate_to_ar(title_clean)
                details_ar = translate_to_ar(raw_text)

                image_url = get_image(entry)

                send_sports_news(title_ar, source, details_ar, image_url)

                seen_links.add(link)
                seen_titles.add(key_title)
                new_count += 1

                time.sleep(2)

        except Exception as e:
            print("⚠️ خطأ في المصدر الرياضي:", url, e)

    return new_count


# ============================
# مواعيد مباريات اليوم (API-FOOTBALL)
# ============================

IMPORTANT_LEAGUES = [
    39,   # Premier League
    140,  # La Liga
    135,  # Serie A
    78,   # Bundesliga
    61,   # Ligue 1
    2,    # Champions League
]


def fetch_today_matches():
    """جلب مباريات اليوم من API-FOOTBALL للدوريات المهمة."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    headers = {
        "x-apisports-key": API_FOOTBALL_KEY,
    }

    matches_by_league: dict[int, list] = {}

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
                league = item.get("league", {})
                fixture = item.get("fixture", {})
                teams = item.get("teams", {})
                goals = item.get("goals", {})

                league_name = league.get("name", "دوري")
                league_id_internal = league.get("id", league_id)

                home = teams.get("home", {}).get("name", "الفريق 1")
                away = teams.get("away", {}).get("name", "الفريق 2")

                status = item.get("fixture", {}).get("status", {}).get("short", "")
                date_iso = fixture.get("date")
                time_str = ""
                if date_iso:
                    try:
                        dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
                        # نعتبر توقيت القدس +2 أو +3 حسب التوقيت، هنا نضيف 2 ساعات تقريبياً
                        dt_local = dt + timedelta(hours=2)
                        time_str = dt_local.strftime("%H:%M")
                    except Exception:
                        pass

                home_g = goals.get("home")
                away_g = goals.get("away")
                result_str = ""
                if home_g is not None and away_g is not None:
                    result_str = f" — النتيجة: {home_g} : {away_g}"

                matches_by_league.setdefault(league_id_internal, []).append(
                    {
                        "league": league_name,
                        "home": home,
                        "away": away,
                        "time": time_str,
                        "status": status,
                        "result": result_str,
                    }
                )

        except Exception as e:
            print("⚠️ خطأ في جلب مباريات الدوري", league_id, e)

    return matches_by_league


def send_today_matches_if_needed():
    global last_matches_day
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if last_matches_day == today:
        return  # تم الإرسال اليوم بالفعل

    matches_by_league = fetch_today_matches()
    if not matches_by_league:
        print("ℹ️ لا توجد مباريات مهمة اليوم (أو فشل الجلب).")
        return

    message_lines = ["🏟 <b>مباريات اليوم (توقيت القدس)</b>\n"]

    for _, matches in matches_by_league.items():
        if not matches:
            continue
        league_name = matches[0]["league"]
        message_lines.append(f"🏆 <b>{league_name}</b>:")
        for m in matches[:10]:  # حد أقصى 10 مباريات لكل دوري
            line = f"• {m['home']} vs {m['away']}"
            if m["time"]:
                line += f" — {m['time']}"
            if m["result"]:
                line += m["result"]
            message_lines.append(line)
        message_lines.append("")

    message_lines.append(
        "📺 ملاحظة: القنوات الناقلة تختلف حسب بلدك وخدمتك التلفزيونية."
    )

    text = "\n".join(message_lines)
    send_photo_or_text(text)  # بدون صورة، نص فقط

    last_matches_day = today
    print("✅ تم إرسال منشور مباريات اليوم.")


# ============================
# حلقة تشغيل البوت
# ============================


def run_bot():
    print("🚀 F90 Sports Bot يعمل الآن…")
    while True:
        shrink_seen_sets()

        # 1) أخبار الرياضة
        new_news = process_sports_feeds()
        if new_news == 0:
            print("⏸ لا أخبار رياضية جديدة الآن.")

        # 2) مباريات اليوم (مرة واحدة باليوم)
        send_today_matches_if_needed()

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
