import os
import logging
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, 
    ContextTypes, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    filters
)
from playwright.async_api import async_playwright

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

DB_URL = os.getenv("DATABASE_URL")

def get_db():
    return psycopg2.connect(DB_URL)

# --- Database Helpers ---
def add_usernames_to_db(usernames):
    conn = get_db()
    cur = conn.cursor()
    for user in usernames:
        cur.execute("INSERT INTO watchlist (username) VALUES (%s) ON CONFLICT DO NOTHING", (user.strip(),))
    conn.commit()
    cur.close()
    conn.close()

def get_watchlist():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, is_active FROM watchlist ORDER BY id ASC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

# --- UI Helpers ---
def main_menu():
    keyboard = [
        [InlineKeyboardButton("➕ Add Account", callback_data='add_help')],
        [InlineKeyboardButton("📋 My Watchlist", callback_data='list')],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✨ *InstaMonitor Pro*\nControl your monitoring here:", 
                                    reply_markup=main_menu(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # MANDATORY to stop loading animation
    
    if query.data == 'add_help':
        await query.edit_message_text("Send me the username(s) separated by commas.\nExample: `user1,user2`", 
                                      parse_mode='Markdown')
    elif query.data == 'list':
        rows = get_watchlist()
        if not rows:
            await query.edit_message_text("Watchlist empty.", reply_markup=main_menu())
            return
        msg = "📊 *Watchlist:*\n\n"
        for idx, (db_id, user, active) in enumerate(rows, 1):
            msg += f"{idx}. {'✅' if active else '❌'} {user}\n"
        msg += "\n*Remove by typing:* /remove 1 2"
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=main_menu())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle comma-separated input
    text = update.message.text
    if ',' in text:
        users = text.split(',')
        add_usernames_to_db(users)
        await update.message.reply_text(f"Added {len(users)} accounts!")

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Logic to remove using list indices
    ids_to_remove = context.args
    # ... (Add your deletion logic here)
    await update.message.reply_text(f"Processing removal for: {ids_to_remove}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("remove", remove_command))
    app.add_handler(CallbackQueryHandler(button_handler)) # Registers the click handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app.run_polling()
