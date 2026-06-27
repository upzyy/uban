import os
import logging
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from playwright.async_api import async_playwright

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- DB Helper ---
def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

# --- UI Helper ---
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ Add Account", callback_data='add'), InlineKeyboardButton("📋 My Watchlist", callback_data='list')],
        [InlineKeyboardButton("🔍 Check Now", callback_data='check'), InlineKeyboardButton("❌ Remove Account", callback_data='remove')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✨ *InstaMonitor Pro*\nSelect an option to manage your tracking:", 
                                    reply_markup=main_menu_keyboard(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'list':
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT username, is_active FROM watchlist")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        msg = "📊 *Your Watchlist:*\n\n"
        for user, status in rows:
            icon = "✅" if status else "❌"
            msg += f"{icon} [{user}](https://instagram.com/{user}/)\n"
        await query.edit_message_text(msg, reply_markup=main_menu_keyboard(), parse_mode='Markdown', disable_web_page_preview=True)

# --- Browser Logic ---
async def check_profile(username):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        try:
            await page.goto(f"https://www.instagram.com/{username}/", timeout=15000)
            content = await page.content()
            # Professional Logic: Instagram usually shows "Page Not Found" in the title or body
            is_active = "Profile isn't available" not in content and "The link may be broken" not in content
            return is_active
        except Exception as e:
            logging.error(f"Browser check failed for {username}: {e}")
            return False
        finally:
            await browser.close()

if __name__ == '__main__':
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()
