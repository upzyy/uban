import os
import logging
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO)
DB_URL = os.getenv("DATABASE_URL")

# --- Browser Check Logic ---
async def check_profile(username):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(f"https://www.instagram.com/{username}/", timeout=15000)
            content = await page.content()
            # Banned/Not Found indicators
            bad_indicators = ["Profile isn't available", "The link may be broken", "removed"]
            return not any(ind in content for ind in bad_indicators)
        except Exception as e:
            logging.error(f"Check failed for {username}: {e}")
            return False
        finally:
            await browser.close()

# --- Background Monitor Job ---
async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT username, is_active FROM watchlist")
    accounts = cur.fetchall()
    
    for username, was_active in accounts:
        is_active = await check_profile(username)
        if not was_active and is_active:
            # Alert and Pin
            msg = await context.bot.send_message(chat_id=os.getenv("OWNER_ID"), text=f"✅ @{username} is back online!")
            await context.bot.pin_chat_message(chat_id=os.getenv("OWNER_ID"), message_id=msg.message_id)
            cur.execute("UPDATE watchlist SET is_active = TRUE WHERE username = %s", (username,))
            conn.commit()
    cur.close()
    conn.close()

# --- Handlers ---
async def add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usernames = [u.strip() for u in update.message.text.split(',')]
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for user in usernames:
        cur.execute("INSERT INTO watchlist (username, is_active) VALUES (%s, FALSE) ON CONFLICT DO NOTHING", (user,))
    conn.commit()
    cur.close()
    conn.close()
    await update.message.reply_text(f"Added {len(usernames)} to watchlist.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    
    # Schedule job to run every hour
    app.job_queue.run_repeating(monitor_job, interval=3600, first=10)
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_handler))
    app.run_polling()
