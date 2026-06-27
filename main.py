import os
import re
import html
import psycopg2
from playwright.async_api import async_playwright
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
    text = text.strip()
    text = text.replace("https://www.instagram.com/", "")
    text = text.replace("http://www.instagram.com/", "")
    text = text.replace("https://instagram.com/", "")
    text = text.replace("http://instagram.com/", "")
    text = text.replace("@", "")
    text = text.split("?")[0]
    text = text.split("/")[0]

    # Instagram allows letters, numbers, underscores, and full stops.
    return re.sub(r"[^A-Za-z0-9._]", "", text)


def account_url(username):
    username = clean_username(username)
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


async def check_instagram(username):
    username = clean_username(username)
    url = account_url(username)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            page = await browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 768},
            )

            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(5000)

            final_url = page.url.lower()
            title = (await page.title()).lower()
            body_text = (await page.locator("body").inner_text()).lower()
            html_content = (await page.content()).lower()

            await browser.close()

        unavailable_signals = [
            "profile isn't available",
            "profile isn’t available",
            "the link may be broken",
            "profile may have been removed",
            "sorry, this page isn't available",
            "sorry, this page isn’t available",
            "page not found",
        ]

        if any(signal in body_text for signal in unavailable_signals):
            return "banned_or_not_found"

        if response and response.status == 404:
            return "banned_or_not_found"

        if "accounts/login" in final_url:
            # Instagram sometimes redirects public profiles to login.
            # This does NOT mean banned.
            return "active_or_login_required"

        username_lower = username.lower()

        active_signals = [
            f"@{username_lower}",
            f'"username":"{username_lower}"',
            f"instagram.com/{username_lower}",
            username_lower,
            "followers",
            "following",
            "posts",
        ]

        if any(signal in body_text for signal in active_signals) or any(signal in html_content for signal in active_signals):
            return "active"

        if "instagram" in title and response and response.status in [200, 301, 302]:
            return "active_or_login_required"

        return "banned_or_not_found"

    except Exception as e:
        print("CHECK ERROR:", e)
        return "error"


def status_icon(status):
    if status == "active":
        return "✅ Active / Unbanned"
    if status == "active_or_login_required":
        return "✅ Active / Login Required"
    if status == "banned_or_not_found":
        return "🚫 Banned / Not Found"
    if status == "error":
        return "⚠️ Error Checking"
    return f"⚠️ {status}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return

    await update.message.reply_text(
        "🛡️ <b>Unban Watcher Bot</b>\n\n"
        "I monitor Instagram usernames and alert you when one becomes active again.\n\n"
        "Choose an option:",
        reply_markup=main_menu(),
        parse_mode="HTML"
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
            "🛡️ <b>Unban Watcher Bot</b>\n\nChoose an option:",
            reply_markup=main_menu(),
            parse_mode="HTML"
        )

    elif data == "add":
        context.user_data[WAITING_FOR_ADD] = True
        await query.edit_message_text(
            "➕ <b>Add Account</b>\n\n"
            "Send me the Instagram username.\n\n"
            "Example:\n"
            "<code>seedra_gharaibeh</code>\n\n"
            "You can also send multiple usernames separated by commas.",
            parse_mode="HTML"
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
            f"🗑 Removed @{html.escape(username)}.",
            reply_markup=main_menu(),
            parse_mode="HTML"
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
                status = await check_instagram(username)

                cur.execute("""
                INSERT INTO tracked(chat_id, username, last_status, profile_url)
                VALUES(%s, %s, %s, %s)
                ON CONFLICT(chat_id, username)
                DO UPDATE SET last_status=EXCLUDED.last_status, profile_url=EXCLUDED.profile_url
                """, (update.effective_chat.id, username, status, url))

                added.append((username, status, url))

    context.user_data[WAITING_FOR_ADD] = False

    msg = "✅ <b>Saved Accounts</b>\n\n"

    for username, status, url in added:
        safe_username = html.escape(username)
        safe_url = html.escape(url)
        msg += f"👤 <b>@{safe_username}</b>\n"
        msg += f"Status: {status_icon(status)}\n"
        msg += f"🔗 <a href=\"{safe_url}\">{safe_url}</a>\n\n"

    await update.message.reply_text(
        msg,
        reply_markup=main_menu(),
        parse_mode="HTML",
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

    msg = "📋 <b>Your Watchlist</b>\n\n"

    for username, status, url in rows:
        username = clean_username(username)
        url = account_url(username)

        safe_username = html.escape(username)
        safe_url = html.escape(url)

        msg += f"👤 <b>@{safe_username}</b>\n"
        msg += f"{status_icon(status)}\n"
        msg += f"🔗 <a href=\"{safe_url}\">{safe_url}</a>\n\n"

    await query.edit_message_text(
        msg,
        reply_markup=main_menu(),
        parse_mode="HTML",
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
        username = clean_username(username)
        keyboard.append([
            InlineKeyboardButton(
                f"🗑 @{username}",
                callback_data=f"remove:{username}"
            )
        ])

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

            msg = "🔄 <b>Current Account Status</b>\n\n"

            for username, old_status in rows:
                username = clean_username(username)
                new_status = await check_instagram(username)
                url = account_url(username)

                cur.execute(
                    "UPDATE tracked SET username=%s, last_status=%s, profile_url=%s WHERE chat_id=%s AND username=%s",
                    (username, new_status, url, chat_id, username)
                )

                safe_username = html.escape(username)
                safe_url = html.escape(url)

                msg += f"👤 <b>@{safe_username}</b>\n"
                msg += f"{status_icon(new_status)}\n"
                msg += f"🔗 <a href=\"{safe_url}\">{safe_url}</a>\n\n"

    await query.edit_message_text(
        msg,
        reply_markup=main_menu(),
        parse_mode="HTML",
        disable_web_page_preview=False
    )


async def monitor(context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id, username, last_status FROM tracked")
            rows = cur.fetchall()

            for chat_id, username, old_status in rows:
                username = clean_username(username)
                new_status = await check_instagram(username)
                url = account_url(username)

                was_banned = old_status in ["banned_or_not_found", "unknown", "error"]
                now_active = new_status in ["active", "active_or_login_required"]

                if was_banned and now_active:
                    safe_username = html.escape(username)
                    safe_url = html.escape(url)

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "✅ <b>Account Unbanned / Active Again</b>\n\n"
                            f"👤 Username: <b>@{safe_username}</b>\n"
                            f"🔗 <a href=\"{safe_url}\">{safe_url}</a>\n\n"
                            "The profile page is reachable again."
                        ),
                        reply_markup=account_buttons(username),
                        parse_mode="HTML",
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
