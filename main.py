import os
import re
import requests
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
OWNER_ID = os.getenv("OWNER_ID")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))

WAITING_FOR_ADD = "waiting_for_add"


def db():
    return psycopg2.connect(DATABASE_URL)


def setup_db():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS tracked (
                chat_id BIGINT NOT NULL,
                username TEXT NOT NULL,
                last_status TEXT DEFAULT 'unknown',
                profile_url TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(chat_id, username)
            )
            """)


def is_owner(update: Update):
    return not OWNER_ID or str(update.effective_user.id) == OWNER_ID


def clean_username(text):
    text = text.replace("@", "").strip()
    return re.sub(r"[^a-zA-Z0-9._]", "", text)


def account_url(username):
    return f"https://www.instagram.com/{username}/"


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Account", callback_data="add")],
        [InlineKeyboardButton("📋 My Watchlist", callback_data="list")],
        [InlineKeyboardButton("🔄 Check Now", callback_data="check_all")],
        [InlineKeyboardButton("🧹 Remove Account", callback_data="remove_menu")],
    ])


def account_buttons(username):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Open Account", url=account_url(username))],
        [InlineKeyboardButton("🗑 Remove", callback_data=f"remove:{username}")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="menu")],
    ])


def check_instagram(username):
    try:
        r = requests.get(
            account_url(username),
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        if r.status_code == 200:
            return "active"
        if r.status_code == 404:
            return "banned_or_not_found"
        if r.status_code == 429:
            return "rate_limited"

        return f"unknown_{r.status_code}"

    except Exception:
        return "error"


def status_icon(status):
    if status == "active":
        return "✅ Active / Unbanned"
    if status == "banned_or_not_found":
        return "🚫 Banned / Not Found"
    if status == "rate_limited":
        return "⏳ Rate Limited"
    return f"⚠️ {status}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return

    await update.message.reply_text(
        "🛡️ **Unban Watcher Bot**\n\n"
        "I can monitor Instagram usernames and alert you when one becomes active again.\n\n"
        "Choose an option:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return

    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = query.message.chat_id

    if data == "menu":
        await query.edit_message_text(
            "🛡️ **Unban Watcher Bot**\n\nChoose an option:",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )

    elif data == "add":
        context.user_data[WAITING_FOR_ADD] = True
        await query.edit_message_text(
            "➕ **Add Account**\n\nSend me the Instagram username.\n\n"
            "Example:\n`seedra_gharaibeh`\n\n"
            "You can also send multiple usernames separated by commas.",
            parse_mode="Markdown"
        )

    elif data == "list":
        await show_list(query, chat_id)

    elif data == "check_all":
        await query.edit_message_text("🔄 Checking all saved accounts...")
        await check_all_now(query, chat_id)

    elif data == "remove_menu":
        await show_remove_menu(query, chat_id)

    elif data.startswith("remove:"):
        username = data.split(":", 1)[1]

        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM tracked WHERE chat_id=%s AND username=%s",
                    (chat_id, username)
                )

        await query.edit_message_text(
            f"🗑 Removed @{username}.",
            reply_markup=main_menu()
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return

    if not context.user_data.get(WAITING_FOR_ADD):
        await update.message.reply_text(
            "Use the buttons below:",
            reply_markup=main_menu()
        )
        return

    raw = update.message.text
    usernames = [clean_username(x) for x in raw.replace("\n", ",").split(",")]
    usernames = [u for u in usernames if u]

    if not usernames:
        await update.message.reply_text("No valid usernames found.")
        return

    added = []

    with db() as conn:
        with conn.cursor() as cur:
            for username in usernames:
                url = account_url(username)
                status = check_instagram(username)

                cur.execute("""
                INSERT INTO tracked(chat_id, username, last_status, profile_url)
                VALUES(%s, %s, %s, %s)
                ON CONFLICT(chat_id, username)
                DO UPDATE SET last_status=EXCLUDED.last_status, profile_url=EXCLUDED.profile_url
                """, (update.effective_chat.id, username, status, url))

                added.append((username, status, url))

    context.user_data[WAITING_FOR_ADD] = False

    msg = "✅ **Saved Accounts**\n\n"
    for username, status, url in added:
        msg += f"👤 @{username}\n"
        msg += f"Status: {status_icon(status)}\n"
        msg += f"Link: {url}\n\n"

    await update.message.reply_text(
        msg,
        reply_markup=main_menu(),
        parse_mode="Markdown",
        disable_web_page_preview=False
    )


async def show_list(query, chat_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, last_status, profile_url FROM tracked WHERE chat_id=%s ORDER BY username",
                (chat_id,)
            )
            rows = cur.fetchall()

    if not rows:
        await query.edit_message_text(
            "📋 Your watchlist is empty.",
            reply_markup=main_menu()
        )
        return

    msg = "📋 **Your Watchlist**\n\n"
    for username, status, url in rows:
        msg += f"👤 @{username}\n"
        msg += f"{status_icon(status)}\n"
        msg += f"🔗 {url}\n\n"

    await query.edit_message_text(
        msg,
        reply_markup=main_menu(),
        parse_mode="Markdown",
        disable_web_page_preview=False
    )


async def show_remove_menu(query, chat_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username FROM tracked WHERE chat_id=%s ORDER BY username",
                (chat_id,)
            )
            rows = cur.fetchall()

    if not rows:
        await query.edit_message_text(
            "There are no accounts to remove.",
            reply_markup=main_menu()
        )
        return

    keyboard = []
    for (username,) in rows:
        keyboard.append([InlineKeyboardButton(f"🗑 @{username}", callback_data=f"remove:{username}")])

    keyboard.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu")])

    await query.edit_message_text(
        "🧹 Choose an account to remove:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def check_all_now(query, chat_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, last_status FROM tracked WHERE chat_id=%s ORDER BY username",
                (chat_id,)
            )
            rows = cur.fetchall()

            if not rows:
                await query.edit_message_text(
                    "No accounts saved yet.",
                    reply_markup=main_menu()
                )
                return

            msg = "🔄 **Current Account Status**\n\n"

            for username, old_status in rows:
                new_status = check_instagram(username)
                url = account_url(username)

                cur.execute(
                    "UPDATE tracked SET last_status=%s, profile_url=%s WHERE chat_id=%s AND username=%s",
                    (new_status, url, chat_id, username)
                )

                msg += f"👤 @{username}\n"
                msg += f"{status_icon(new_status)}\n"
                msg += f"🔗 {url}\n\n"

    await query.edit_message_text(
        msg,
        reply_markup=main_menu(),
        parse_mode="Markdown",
        disable_web_page_preview=False
    )


async def monitor(context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id, username, last_status FROM tracked")
            rows = cur.fetchall()

            for chat_id, username, old_status in rows:
                new_status = check_instagram(username)
                url = account_url(username)

                if old_status != "active" and new_status == "active":
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "✅ **Account Unbanned / Active Again**\n\n"
                            f"👤 Username: @{username}\n"
                            f"🔗 Link: {url}\n\n"
                            "The account is reachable again."
                        ),
                        reply_markup=account_buttons(username),
                        parse_mode="Markdown",
                        disable_web_page_preview=False
                    )

                cur.execute(
                    "UPDATE tracked SET last_status=%s, profile_url=%s WHERE chat_id=%s AND username=%s",
                    (new_status, url, chat_id, username)
                )


def main():
    setup_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.job_queue.run_repeating(monitor, interval=CHECK_INTERVAL, first=10)

    print("Unban Watcher Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
