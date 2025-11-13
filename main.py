import requests
from telegram.ext import Updater, CommandHandler
from flask import Flask
import threading
import os
from datetime import datetime

# ===============================
#   إعدادات البوت
# ===============================

BOT_TOKEN = os.getenv("BOT_TOKEN", "ضع_توكن_البوت_هنا")
CHAT_ID = os.getenv("CHAT_ID", "@F90Sports")

API_KEY = os.getenv("API_FOOTBALL_KEY", "ضع_مفتاح_API_هنا")
BASE_URL = "https://v3.football.api-sports.io"

# ===============================
#   جلب مباريات اليوم
# ===============================

def get_today_matches():
    url = f"{BASE_URL}/fixtures"
    params = {"date": datetime.utcnow().strftime("%Y-%m-%d")}
    headers = {"x-apisports-key": API_KEY}

    r = requests.get(url, headers=headers, params=params)
    data = r.json()

    if "response" not in data:
        return None

    matches = data["response"]
    results = []

    for m in matches:
        league = m["league"]["name"]
        home = m["teams"]["home"]["name"]
        away = m["teams"]["away"]["name"]
        home_logo = m["teams"]["home"]["logo"]
        away_logo = m["teams"]["away"]["logo"]
        time = m["fixture"]["date"][11:16]

        status = m["fixture"]["status"]["short"]

        if status in ["FT"]:
            score = f"{m['goals']['home']} - {m['goals']['away']}"
        else:
            score = "لم تبدأ بعد"

        msg = f"""
⚽ <b>{league}</b>

🏟 <b>{home}</b> vs <b>{away}</b>
⏰ الساعة: {time}
📊 النتيجة: {score}

📺 القنوات الناقلة:
- بي إن سبورتس
- قنوات محلية حسب الدولة

🎥 بث مباشر:
<a href='https://yalla-shoot.video/'>اضغط هنا للمشاهدة</a>
"""

        results.append({
            "text": msg,
            "home_logo": home_logo,
            "away_logo": away_logo
        })

    return results

# ===============================
#   إرسال مباريات اليوم
# ===============================

def send_today(update, context):
    matches = get_today_matches()

    if not matches:
        update.message.reply_text("❌ لا توجد مباريات اليوم")
        return

    for m in matches:
        try:
            context.bot.sendPhoto(
                chat_id=update.effective_chat.id,
                photo=m["home_logo"],
                caption=m["text"],
                parse_mode="HTML"
            )
        except:
            update.message.reply_text(m["text"], parse_mode="HTML")

# ===============================
#   أوامر البوت
# ===============================

def start(update, context):
    update.message.reply_text("مرحباً! أرسل /today لعرض مباريات اليوم ⚽🔥")

def today(update, context):
    send_today(update, context)

# ===============================
#   تشغيل البوت
# ===============================

updater = Updater(BOT_TOKEN, use_context=True)
dp = updater.dispatcher

dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("today", today))

# ===============================
#   Flask للحفاظ على نشاط Render
# ===============================

app = Flask(__name__)

@app.route("/")
def home():
    return "F90 Sports Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# ===============================
#   تشغيل كل شيء
# ===============================

def start_all():
    threading.Thread(target=run_flask).start()
    updater.start_polling()
    print("⚽ Sports Bot Running...")

if __name__ == "__main__":
    start_all()
