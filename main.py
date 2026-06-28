import os
import logging
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, 
    CallbackQueryHandler, MessageHandler, filters
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")

# --- UI Helper ---
def get_main_menu():
    """Returns the persistent menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("➕ Add Account", callback_data='add_help')],
        [InlineKeyboardButton("📋 My Watchlist", callback_data='list')],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✨ *InstaMonitor Pro*\nControl your monitoring here:", 
        reply_markup=get_main_menu(), 
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # MANDATORY: Stops loading animation
    
    if query.data == 'add_help':
        await query.edit_message_text(
            "Send me the username(s) separated by commas.\nExample: `user1,user2`", 
            reply_markup=get_main_menu(), # Re-attach to prevent loss
            parse_mode='Markdown'
        )
    elif query.data == 'list':
        # Database logic would go here
        await query.edit_message_text(
            "📊 *Your Watchlist is empty.*", 
            reply_markup=get_main_menu(), 
            parse_mode='Markdown'
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # Simple processing logic
    usernames = [u.strip() for u in text.split(',')]
    await update.message.reply_text(
        f"✅ Added {len(usernames)} account(s).",
        reply_markup=get_main_menu()
    )

if __name__ == '__main__':
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    # Filter text messages, ensuring privacy mode is off in BotFather
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app.run_polling()
