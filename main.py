import os
import logging
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, 
    CallbackQueryHandler, MessageHandler, filters
)

# Setup logging to see everything in Railway
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    logger.info(f"Received message: {text}") # THIS WILL SHOW IN RAILWAY LOGS
    
    # Process comma-separated list
    usernames = [u.strip() for u in text.split(',')]
    
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for user in usernames:
        try:
            cur.execute("INSERT INTO watchlist (username) VALUES (%s) ON CONFLICT DO NOTHING", (user,))
        except Exception as e:
            logger.error(f"Database error: {e}")
    conn.commit()
    cur.close()
    conn.close()
    
    await update.message.reply_text(f"✅ Added {len(usernames)} account(s) to your watchlist.")

if __name__ == '__main__':
    # Build application
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    
    # Register handlers
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Bot active. Send me usernames separated by commas.")))
    # This filter captures ANY text that isn't a command
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Bot is polling...")
    app.run_polling()
