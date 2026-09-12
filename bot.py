import logging
import asyncio
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

from config import BOT_TOKEN, DEFAULT_TRADE_AMOUNT, DEFAULT_TRADE_TYPE, ADMIN_IDS
from db import (
    get_user, update_user, add_user_log, get_all_users,
    is_user_subscribed, grant_subscription, revoke_subscription,
    get_global_settings, update_global_settings
)
from security import encrypt_password, decrypt_password
from zenquant_api import ZenQuantClient
from scheduler import schedule_user_automation, stop_user_automation, execute_3h_auto_cycle, init_all_user_schedulers

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation States
WAITING_PHONE, WAITING_PASSWORD = range(2)

# --- Helper Functions ---

def get_client_for_user(user: dict) -> ZenQuantClient:
    """Creates an authenticated ZenQuantClient instance for the user."""
    client = ZenQuantClient()
    phone = user.get("phone", "")
    encrypted_pwd = user.get("encrypted_password", "")
    country_code = user.get("country_code", "+91")
    
    if encrypted_pwd:
        password = decrypt_password(encrypted_pwd)
        if phone and password:
            ok, msg, token = client.login(phone, password, country_code)
            if not ok:
                logger.warning(f"Client auto-login failed for user {phone}: {msg}")
    return client

def build_dashboard_text(user: dict, username: str, chat_id: int) -> str:
    phone = user.get("phone", "")
    connected_str = f"`{phone[:4]}****{phone[-2:]}` (Connected)" if phone and user.get("connected") else "Not Connected"
    amount = user.get("trade_amount", DEFAULT_TRADE_AMOUNT)
    amount_str = f"${amount:.2f} USD" if user.get("connected") else "Not Set"
    trade_type = user.get("trade_type", DEFAULT_TRADE_TYPE)
    auto_str = "ENABLED (3H Loop)" if user.get("auto_enabled") else "DISABLED"
    country = user.get("country_code", "+91")

    sub_active = is_user_subscribed(chat_id)
    if chat_id in ADMIN_IDS:
        sub_str = "VIP ADMIN (Unlimited)"
    elif sub_active:
        expiry_str = user.get("subscription_expiry", "Active")
        sub_str = f"ACTIVE (Expires: `{expiry_str}`)"
    else:
        sub_str = "INACTIVE (Buy Plan to Unlock Auto-Inject)"

    return (
        "**ZENQUANT AUTO-TRADER**\n"
        "═════════════════════════\n"
        f"• User: @{username}\n"
        f"• Country: India (`{country}`)\n"
        f"• Account: {connected_str}\n"
        f"• Subscription: {sub_str}\n"
        "─────────────────────────\n"
        f"• Inject Capital: `{amount_str}`\n"
        f"• Strategy Plan: `{trade_type}`\n"
        f"• Auto-Trade Loop: `{auto_str}`\n"
        f"• Server Status: `Active 24/7`\n"
        "═════════════════════════\n"
        "*Select an option below to manage your bot:*"
    )

def build_help_text() -> str:
    return (
        "**ZENQUANT BOT GUIDE**\n"
        "═════════════════════════\n"
        "ZenQuant Automated Trading System guide:\n\n"
        "• `/login` - ZenQuant account sign in\n"
        "• `/inject` - Instant $50 trade injection\n"
        "• `/claim` - Finished yield profit claim\n"
        "• `/status` - Live balance & countdown timer\n"
        "• `/history` - Trade history (Bot vs Manual)\n"
        "• `/auto` - Toggle 3-hour auto-loop ON/OFF\n"
        "• `/buy` - Buy 3-Hour Auto-Inject Plan\n"
        "• `/amount` - Set custom trade amount\n"
        "• `/logs` - Recent background execution logs\n\n"
        "*Tip: Tap [/] Menu button at bottom left anytime!*\n"
        "═════════════════════════"
    )

def build_subscription_text() -> str:
    settings = get_global_settings()
    addr = settings.get("usdt_bep20_address", "0x7a39F999812A2789123048991212889218291283")
    admin_uname = settings.get("admin_username", "@ZenQuantSupport")
    rates = settings.get("subscription_rates", "")

    return (
        "**ZENQUANT AUTO-INJECT SUBSCRIPTION**\n"
        "═════════════════════════\n"
        "Auto 3-Hour Injection feature activate karne ke liye plan purchase karein:\n\n"
        "**SUBSCRIPTION RATE CHART**:\n"
        f"{rates}\n"
        "─────────────────────────\n"
        "**USDT BEP-20 DEPOSIT ADDRESS**:\n"
        f"`{addr}`\n"
        "*(Address copy karne ke liye tap karein)*\n"
        "─────────────────────────\n"
        "**ACTIVATION INSTRUCTIONS**:\n"
        "1. Desired plan select karke USDT BEP-20 address par exact payment bhejen.\n"
        "2. Payment hone ke baad **Payment Screenshot** is bot me Photo ki tarah send kar dein!\n"
        f"3. Bot direct admin ({admin_uname}) ko verification ke liye bhej dega aur aapka plan approve ho jayega.\n"
        "═════════════════════════"
    )

def get_back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Back to Main Dashboard", callback_data="show_dashboard")]])

def get_dashboard_buttons(user: dict, chat_id: int) -> InlineKeyboardMarkup:
    is_conn = user.get("connected", False)
    login_label = "Account Connected" if is_conn else "Login Account"
    auto_label = "Auto Loop: ON" if user.get("auto_enabled") else "Auto Loop: OFF"
    
    keyboard = [
        [
            InlineKeyboardButton(login_label, callback_data="start_login"),
            InlineKeyboardButton("Live Status", callback_data="show_status")
        ],
        [
            InlineKeyboardButton("Inject $50 Now", callback_data="do_inject"),
            InlineKeyboardButton("Trade History", callback_data="show_history")
        ],
        [
            InlineKeyboardButton(auto_label, callback_data="toggle_auto"),
            InlineKeyboardButton("Buy Subscription", callback_data="show_subscription")
        ],
        [
            InlineKeyboardButton("Guide & Help", callback_data="show_help")
        ]
    ]
    if chat_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("Admin Panel", callback_data="admin_panel")])
        
    return InlineKeyboardMarkup(keyboard)

# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_target = update.effective_message
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    user = get_user(chat_id)
    update_user(chat_id, {"telegram_username": username})

    dash_msg = build_dashboard_text(user, username, chat_id)
    reply_markup = get_dashboard_buttons(user, chat_id)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(dash_msg, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await msg_target.reply_text(dash_msg, parse_mode="Markdown", reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_callback = update.callback_query is not None
    help_txt = build_help_text()
    if is_callback:
        await update.callback_query.message.edit_text(help_txt, parse_mode="Markdown", reply_markup=get_back_button())
    else:
        await update.effective_message.reply_text(help_txt, parse_mode="Markdown", reply_markup=get_back_button())

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_callback = update.callback_query is not None
    sub_txt = build_subscription_text()
    if is_callback:
        await update.callback_query.message.edit_text(sub_txt, parse_mode="Markdown", reply_markup=get_back_button())
    else:
        await update.effective_message.reply_text(sub_txt, parse_mode="Markdown", reply_markup=get_back_button())

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    is_callback = update.callback_query is not None

    if not user.get("connected"):
        txt = "Account connected nahi hai! Pehle `/login` karein."
        if is_callback:
            await update.callback_query.message.edit_text(txt, reply_markup=get_back_button())
        else:
            await update.effective_message.reply_text(txt, reply_markup=get_back_button())
        return

    wait_txt = "Account balance aur live timer check ho raha hai..."
    if is_callback:
        msg_wait = update.callback_query.message
        await msg_wait.edit_text(wait_txt)
    else:
        msg_wait = await update.effective_message.reply_text(wait_txt)

    def fetch_status():
        client = get_client_for_user(user)
        return client.get_account_status()

    status_data = await asyncio.to_thread(fetch_status)

    avail = status_data.get("available_balance", 0.0)
    holdings = status_data.get("total_holdings", 0.0)
    tot_prof = status_data.get("total_profit", 0.0)
    pos = status_data.get("active_position")

    bot_orders = user.get("bot_order_ids", [])

    if pos:
        order_id = pos.get("order_id", "N/A")
        if order_id in bot_orders:
            source_tag = "[BOT AUTO-INJECT]"
        else:
            source_tag = "[MANUAL INJECT]"

        timer_str = pos.get("remaining_formatted", "3 Hours")
        amount_val = pos.get("price", 50.0)
        yield_val = pos.get("est_yield", 0.25)
        start_time = pos.get("start_time", "Recent")

        pos_info = (
            f"• Order ID: `{order_id}`\n"
            f"• Source: `{source_tag}`\n"
            f"• Plan: `{user.get('trade_type', 'PLUS')}` (0.5% Yield)\n"
            f"• Capital: `${amount_val:.2f} USD`\n"
            f"• Est. Profit: `${yield_val:.4f} USD`\n"
            f"• Start Time: `{start_time}`\n"
            f"• Countdown Timer: `{timer_str}`"
        )
    else:
        pos_info = "*Koi active position nahi hai abhi. Quick inject karein!*"

    phone = user.get("phone", "")
    phone_mask = f"{phone[:4]}****{phone[-2:]}" if len(phone) >= 6 else phone

    msg = (
        "**ACCOUNT & LIVE POSITION**\n"
        "═════════════════════════\n"
        f"• Account: `{phone_mask}`\n"
        f"• Available Balance: `${avail:.2f} USD`\n"
        f"• Locked Holdings: `${holdings:.2f} USD`\n"
        f"• Total Assets: `${(avail + holdings):.2f} USD`\n"
        f"• Total Profit Earned: `${tot_prof:.2f} USD`\n"
        "─────────────────────────\n"
        f"**ACTIVE POSITION DETAILS**:\n{pos_info}\n"
        "─────────────────────────\n"
        f"• 3-Hour Auto Loop: `{'ENABLED' if user.get('auto_enabled') else 'DISABLED'}`\n"
        "═════════════════════════"
    )
    await msg_wait.edit_text(msg, parse_mode="Markdown", reply_markup=get_back_button())

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    is_callback = update.callback_query is not None

    if not user.get("connected"):
        txt = "Pehle `/login` karein."
        if is_callback:
            await update.callback_query.message.edit_text(txt, reply_markup=get_back_button())
        else:
            await update.effective_message.reply_text(txt, reply_markup=get_back_button())
        return

    phone = user.get("phone", "")
    phone_mask = f"{phone[:4]}****{phone[-2:]}" if len(phone) >= 6 else phone
    bot_orders = user.get("bot_order_ids", [])

    wait_txt = "Recent trade history data aa raha hai..."
    if is_callback:
        msg_wait = update.callback_query.message
        await msg_wait.edit_text(wait_txt)
    else:
        msg_wait = await update.effective_message.reply_text(wait_txt)

    def fetch_history():
        client = get_client_for_user(user)
        return client.get_deal_list(page=1, size=15)

    orders_list = await asyncio.to_thread(fetch_history)

    history_lines = []
    if orders_list:
        for o in orders_list:
            ordersn = o.get("ordersn", "")
            price = o.get("price", 50)
            time_str = o.get("time", "N/A")
            is_rec = o.get("is_receive", 0)
            status_str = "Claimed" if is_rec == 1 else "Active/In Progress"
            
            if ordersn in bot_orders:
                tag = "[BOT AUTO-INJECT]"
            else:
                tag = "[MANUAL INJECT]"

            history_lines.append(f"{tag} {time_str} - ${price:.2f} USD ({status_str})")
    
    if not history_lines:
        logs = user.get("logs", [])
        history_lines = logs[-10:] if logs else ["Koi history nahi mili."]

    formatted_history = "\n".join(history_lines[:12])
    msg = (
        "**TRADE & INJECTION HISTORY**\n"
        "═════════════════════════\n"
        f"• Account: `{phone_mask}`\n"
        "• Tag: [BOT AUTO-INJECT] | [MANUAL INJECT]\n"
        "─────────────────────────\n"
        f"```\n{formatted_history}\n```\n"
        "═════════════════════════"
    )
    await msg_wait.edit_text(msg, parse_mode="Markdown", reply_markup=get_back_button())

async def injections_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await history_command(update, context)

async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await history_command(update, context)

async def inject_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    is_callback = update.callback_query is not None

    if not user.get("connected"):
        txt = "Pehle `/login` karein."
        if is_callback:
            await update.callback_query.message.edit_text(txt, reply_markup=get_back_button())
        else:
            await update.effective_message.reply_text(txt, reply_markup=get_back_button())
        return

    amount = user.get("trade_amount", 50)
    trade_type = user.get("trade_type", "PLUS")

    wait_txt = f"${amount:.2f} USD injection submit ho raha hai (5-10 sec verification)..."
    if is_callback:
        msg_wait = update.callback_query.message
        await msg_wait.edit_text(wait_txt)
    else:
        msg_wait = await update.effective_message.reply_text(wait_txt)
    
    def run_injection():
        client = get_client_for_user(user)
        return client.confirm_injection(amount, trade_type)

    ok, msg, data = await asyncio.to_thread(run_injection)

    if ok:
        order_id = data.get("order_id", "ZQ-LIVE")
        update_user(chat_id, {
            "last_order_id": order_id,
            "last_cycle_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        add_user_log(chat_id, f"[MANUAL INJECT] Injected ${amount:.2f} into {trade_type} (Order: {order_id})")
        
        reply = (
            "**INJECTION SUCCESSFUL!**\n"
            "═════════════════════════\n"
            f"• Order ID: `{order_id}`\n"
            f"• Source: `[MANUAL INJECT]`\n"
            f"• Capital Injected: `${amount:.2f} USD`\n"
            f"• Strategy Plan: `{trade_type}`\n"
            f"• Lock Duration: `3 Hours`\n"
            "─────────────────────────\n"
            "*3-hour timer start ho gaya. Profit 3 hour baad claim karke re-inject ho jayega.*\n"
            "═════════════════════════"
        )
        await msg_wait.edit_text(reply, parse_mode="Markdown", reply_markup=get_back_button())
    else:
        await msg_wait.edit_text(f"INJECTION FAILED: {msg}", reply_markup=get_back_button())

async def claim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    is_callback = update.callback_query is not None

    if not user.get("connected"):
        txt = "Pehle `/login` karein."
        if is_callback:
            await update.callback_query.message.edit_text(txt, reply_markup=get_back_button())
        else:
            await update.effective_message.reply_text(txt, reply_markup=get_back_button())
        return

    order_id = user.get("last_order_id")
    wait_txt = "3-hour cycle reward claim ho raha hai..."
    if is_callback:
        msg_wait = update.callback_query.message
        await msg_wait.edit_text(wait_txt)
    else:
        msg_wait = await update.effective_message.reply_text(wait_txt)

    def run_claim():
        client = get_client_for_user(user)
        return client.claim_reward(order_id)

    ok, msg, reward = await asyncio.to_thread(run_claim)

    if ok:
        add_user_log(chat_id, f"[MANUAL CLAIM] Claimed ${reward:.2f} yield for Order: {order_id}")
        await msg_wait.edit_text(
            f"**CLAIM SUCCESSFUL!**\n"
            "═════════════════════════\n"
            f"• Claimed Yield: `${reward:.2f} USD`\n"
            f"• Principal Balance: Available Balance me wapas aa gaya.\n"
            "═════════════════════════",
            parse_mode="Markdown",
            reply_markup=get_back_button()
        )
    else:
        await msg_wait.edit_text(f"CLAIM FAIL: {msg}", reply_markup=get_back_button())

async def amount_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_target = update.effective_message
    chat_id = update.effective_chat.id
    if not context.args:
        await msg_target.reply_text("Usage: `/amount 50` (USD amount enter karein)", parse_mode="Markdown")
        return
    try:
        val = float(context.args[0])
        if val < 10:
            await msg_target.reply_text("Minimum injection amount 10 USD hai.")
            return
        update_user(chat_id, {"trade_amount": val})
        await msg_target.reply_text(f"Injection amount `${val:.2f} USD` set ho gaya.", parse_mode="Markdown")
    except ValueError:
        await msg_target.reply_text("Sahi format enter karein. Example: `/amount 50`", parse_mode="Markdown")

async def type_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_target = update.effective_message
    chat_id = update.effective_chat.id
    if not context.args:
        await msg_target.reply_text("Usage: `/type 1` (3 HOUR) ya `/type 2` (PLUS)", parse_mode="Markdown")
        return
    t_val = context.args[0]
    if t_val == "1" or t_val.lower() == "3hour":
        ttype = "3 HOUR"
    elif t_val == "2" or t_val.lower() == "plus":
        ttype = "PLUS"
    else:
        await msg_target.reply_text("Sahi type select karein: `1` (3 HOUR), `2` (PLUS)", parse_mode="Markdown")
        return

    update_user(chat_id, {"trade_type": ttype})
    await msg_target.reply_text(f"Trade plan type `{ttype}` set ho gaya.", parse_mode="Markdown")

async def auto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_target = update.effective_message
    chat_id = update.effective_chat.id
    user = get_user(chat_id)

    if not context.args:
        status_str = "ENABLED" if user.get("auto_enabled") else "DISABLED"
        await msg_target.reply_text(f"3-hour automation abhi `{status_str}` hai. Usage: `/auto on` ya `/auto off`", parse_mode="Markdown")
        return

    arg = context.args[0].lower()
    if arg in ["on", "enable", "1"]:
        if not user.get("connected"):
            await msg_target.reply_text("Pehle `/login` karein.")
            return
        if not is_user_subscribed(chat_id):
            sub_txt = build_subscription_text()
            await msg_target.reply_text(
                f"**SUBSCRIPTION REQUIRED!**\n\nAuto 3-Hour Injection feature only active paid subscribers ke liye hai.\n\n{sub_txt}",
                parse_mode="Markdown",
                reply_markup=get_back_button()
            )
            return
        update_user(chat_id, {"auto_enabled": True})
        schedule_user_automation(chat_id, context.application)
        await msg_target.reply_text("**3-Hour Automation ENABLED!**\nBot har 3 ghante me auto-claim karke re-inject karega.", parse_mode="Markdown")
    elif arg in ["off", "disable", "0"]:
        update_user(chat_id, {"auto_enabled": False})
        stop_user_automation(chat_id)
        await msg_target.reply_text("**Automation DISABLED.** Auto cycle paused.", parse_mode="Markdown")
    else:
        await msg_target.reply_text("Usage: `/auto on` ya `/auto off`", parse_mode="Markdown")

async def runnow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_target = update.effective_message
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user.get("connected"):
        await msg_target.reply_text("Pehle `/login` karein.")
        return

    await msg_target.reply_text("1 full cycle execute ho raha hai (Claim -> Inject -> Schedule)...")
    await asyncio.to_thread(execute_3h_auto_cycle, chat_id, context.application)

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_target = update.effective_message
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    logs = user.get("logs", [])
    if not logs:
        await msg_target.reply_text("Koi activity logs nahi hain abhi.")
        return

    recent_logs = "\n".join(logs[-15:])
    await msg_target.reply_text(f"**RECENT BOT LOGS**\n\n```\n{recent_logs}\n```", parse_mode="Markdown")

# --- Admin Panel Commands ---

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ADMIN_IDS:
        await update.effective_message.reply_text("Akses denied: Aap admin nahi hain.")
        return

    users_db = get_all_users()
    total_users = len(users_db)
    active_subs = sum(1 for cid in users_db if is_user_subscribed(int(cid)))
    active_autos = sum(1 for u in users_db.values() if u.get("auto_enabled"))
    settings = get_global_settings()

    admin_text = (
        "**ZENQUANT ADMIN PANEL**\n"
        "═════════════════════════\n"
        f"• Total Registered Users: `{total_users}`\n"
        f"• Active Paid Subscriptions: `{active_subs}`\n"
        f"• Active Auto-Loops: `{active_autos}`\n"
        "─────────────────────────\n"
        f"• USDT Address: `{settings.get('usdt_bep20_address')}`\n"
        f"• Support Admin: `{settings.get('admin_username')}`\n"
        "═════════════════════════\n"
        "Select an admin command to configure:"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Broadcast Msg", callback_data="admin_broadcast_info"),
            InlineKeyboardButton("Subscribed Users", callback_data="admin_sub_list")
        ],
        [
            InlineKeyboardButton("Update USDT Addr", callback_data="admin_edit_usdt_info"),
            InlineKeyboardButton("Update Support Admin", callback_data="admin_edit_uname_info")
        ],
        [
            InlineKeyboardButton("Update Rate Chart", callback_data="admin_edit_rates_info"),
            InlineKeyboardButton("Grant Subscription", callback_data="admin_grant_info")
        ],
        [
            InlineKeyboardButton("Back to Main Dashboard", callback_data="show_dashboard")
        ]
    ])

    if update.callback_query:
        await update.callback_query.message.edit_text(admin_text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(admin_text, parse_mode="Markdown", reply_markup=keyboard)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ADMIN_IDS:
        return

    if not context.args:
        await update.effective_message.reply_text("Usage: `/broadcast Hello Users!`", parse_mode="Markdown")
        return

    btext = " ".join(context.args)
    users_db = get_all_users()
    success = 0
    fail = 0

    await update.effective_message.reply_text(f"Broadcasting message to {len(users_db)} users...")

    for cid_str in users_db.keys():
        try:
            uid = int(cid_str)
            await context.bot.send_message(
                chat_id=uid,
                text=f"**ANNOUNCEMENT FROM ADMIN**\n═════════════════════════\n{btext}\n═════════════════════════",
                parse_mode="Markdown"
            )
            success += 1
        except Exception:
            fail += 1

    await update.effective_message.reply_text(f"Broadcast Complete!\n• Success: {success}\n• Failed: {fail}")

async def setusdt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ADMIN_IDS:
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: `/setusdt 0xYourBEP20Address...`", parse_mode="Markdown")
        return
    new_addr = context.args[0].strip()
    update_global_settings({"usdt_bep20_address": new_addr})
    await update.effective_message.reply_text(f"USDT BEP-20 address updated to:\n`{new_addr}`", parse_mode="Markdown")

async def setsupport_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ADMIN_IDS:
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: `/setsupport @AdminUsername`", parse_mode="Markdown")
        return
    uname = context.args[0].strip()
    if not uname.startswith("@"):
        uname = f"@{uname}"
    update_global_settings({"admin_username": uname})
    await update.effective_message.reply_text(f"Admin support username updated to: `{uname}`", parse_mode="Markdown")

async def setrates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ADMIN_IDS:
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: `/setrates Rate chart text here`", parse_mode="Markdown")
        return
    rates_text = " ".join(context.args)
    update_global_settings({"subscription_rates": rates_text})
    await update.effective_message.reply_text("Subscription rate chart updated!", parse_mode="Markdown")

async def grant_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.effective_message.reply_text("Usage: `/grant <USER_ID> <DAYS>` (e.g. `/grant 8558893620 10`)", parse_mode="Markdown")
        return
    try:
        target_uid = int(context.args[0])
        days = int(context.args[1])
        expiry_str = grant_subscription(target_uid, days)
        
        user = get_user(target_uid)
        if user.get("connected"):
            schedule_user_automation(target_uid, context.application)
            
        await update.effective_message.reply_text(
            f"User `{target_uid}` ko **{days} Days** ka subscription grant ho gaya hai!\nExpires: `{expiry_str}`",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text=f"**SUBSCRIPTION ACTIVATED!**\nAdmin ne aapka plan `{days} Days` ke liye activate kar diya hai! Expiry: `{expiry_str}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    except ValueError:
        await update.effective_message.reply_text("User ID aur Days numbers hone chahiye.")

async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.effective_message.reply_text("Usage: `/reject <USER_ID> <REJECTION REASON>`\nExample: `/reject 8558893620 Payment TXID not received in wallet`", parse_mode="Markdown")
        return
    try:
        target_uid = int(context.args[0])
        reason = " ".join(context.args[1:])
        
        settings = get_global_settings()
        admin_uname = settings.get("admin_username", "@ZenQuantSupport")
        
        reject_notify = (
            "**PAYMENT REJECTED**\n"
            "═════════════════════════\n"
            "Aapka payment screenshot reject ho gaya hai.\n\n"
            f"• **Reason**: {reason}\n"
            f"• Contact Admin: {admin_uname}\n"
            "═════════════════════════"
        )
        await context.bot.send_message(chat_id=target_uid, text=reject_notify, parse_mode="Markdown")
        await update.effective_message.reply_text(f"Rejection reason sent to user `{target_uid}`:\n`{reason}`", parse_mode="Markdown")
    except Exception as e:
        await update.effective_message.reply_text(f"Rejection fail: {e}")

async def revoke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ADMIN_IDS:
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: `/revoke <USER_ID>`", parse_mode="Markdown")
        return
    try:
        target_uid = int(context.args[0])
        revoke_subscription(target_uid)
        stop_user_automation(target_uid)
        await update.effective_message.reply_text(f"User `{target_uid}` ka subscription revoke ho gaya.", parse_mode="Markdown")
    except ValueError:
        await update.effective_message.reply_text("User ID number hone chahiye.")

# --- Photo Payment Proof Handler ---

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    photos = update.message.photo
    if not photos:
        return

    photo_file_id = photos[-1].file_id

    await update.message.reply_text(
        "**PAYMENT SCREENSHOT RECEIVED!**\n"
        "═════════════════════════\n"
        "Aapka screenshot admin verification ke liye submit ho gaya hai.\n"
        "Verification complete hote hi aapka 3-Hour Auto-Inject plan activate ho jayega!",
        parse_mode="Markdown",
        reply_markup=get_back_button()
    )

    caption_text = (
        "**NEW PAYMENT PROOF RECEIVED**\n"
        "═════════════════════════\n"
        f"• User: @{username}\n"
        f"• Telegram ID: `{chat_id}`\n"
        f"• Time: `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
        "═════════════════════════\n"
        "Select duration to Approve or Reject:"
    )

    approve_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Approve Plan", callback_data=f"approve_pay_{chat_id}"),
            InlineKeyboardButton("Reject Payment", callback_data=f"reject_pay_{chat_id}")
        ]
    ])

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=photo_file_id,
                caption=caption_text,
                parse_mode="Markdown",
                reply_markup=approve_keyboard
            )
        except Exception as e:
            logger.error(f"Failed to send payment proof to admin {admin_id}: {e}")

# --- Conversation Login Flow ---

async def start_login_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    prompt_text = "Apna **ZenQuant Phone Number ya Account** enter karein (e.g. `9084722241`):"
    if query:
        await query.answer()
        await query.message.reply_text(prompt_text, parse_mode="Markdown")
    elif update.effective_message:
        await update.effective_message.reply_text(prompt_text, parse_mode="Markdown")
    return WAITING_PHONE

async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_target = update.effective_message
    phone = msg_target.text.strip().replace(" ", "")
    if len(phone) < 5:
        await msg_target.reply_text("Sahi phone/account number enter karein:")
        return WAITING_PHONE

    context.user_data["phone"] = phone
    await msg_target.reply_text("Apna **ZenQuant Password** enter karein:\n*(Encrypted with AES-256)*", parse_mode="Markdown")
    return WAITING_PASSWORD

async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_target = update.effective_message
    password = msg_target.text.strip()
    chat_id = update.effective_chat.id
    phone = context.user_data.get("phone", "")

    msg_wait = await msg_target.reply_text("Account verify aur login ho raha hai...")

    def run_auth():
        client = ZenQuantClient()
        return client.login(phone, password)

    ok, msg, token = await asyncio.to_thread(run_auth)

    if ok:
        enc_pwd = encrypt_password(password)
        
        # Admin gets auto-enabled subscription
        if chat_id in ADMIN_IDS:
            grant_subscription(chat_id, 365)

        update_user(chat_id, {
            "phone": phone,
            "encrypted_password": enc_pwd,
            "connected": True
        })
        
        if is_user_subscribed(chat_id):
            update_user(chat_id, {"auto_enabled": True})
            schedule_user_automation(chat_id, context.application)

        add_user_log(chat_id, "Logged in ZenQuant account successfully.")

        phone_mask = f"{phone[:4]}****{phone[-2:]}" if len(phone) >= 6 else phone
        sub_status = "ENABLED" if is_user_subscribed(chat_id) else "INACTIVE (Buy Subscription to Unlock)"
        success_text = (
            "**ACCOUNT CONNECTED SUCCESSFULLY!**\n"
            "═════════════════════════\n"
            f"• Account: `{phone_mask}`\n"
            f"• Security: `AES-256 Encrypted`\n"
            f"• 3-Hour Auto Loop: `{sub_status}`\n"
            "─────────────────────────\n"
            "*ZenQuant account verify aur link ho gaya hai!*"
        )
        await msg_wait.edit_text(success_text, parse_mode="Markdown")
    else:
        add_user_log(chat_id, f"Login Failed for '{phone}': {msg}")
        await msg_wait.edit_text(f"LOGIN FAIL: {msg}\n\nDobara `/login` try karein.", parse_mode="Markdown")

    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_target = update.effective_message
    if msg_target:
        await msg_target.reply_text("Login cancel ho gaya.")
    return ConversationHandler.END

# --- Callback Handler ---

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    data = query.data

    if data == "show_dashboard":
        chat_id = update.effective_chat.id
        username = update.effective_user.username or update.effective_user.first_name
        user = get_user(chat_id)
        dash_msg = build_dashboard_text(user, username, chat_id)
        reply_markup = get_dashboard_buttons(user, chat_id)
        await query.message.edit_text(dash_msg, parse_mode="Markdown", reply_markup=reply_markup)
    elif data == "show_help":
        await help_command(update, context)
    elif data == "show_subscription":
        await buy_command(update, context)
    elif data == "show_status":
        await status_command(update, context)
    elif data == "show_history":
        await history_command(update, context)
    elif data == "do_inject":
        await inject_command(update, context)
    elif data == "admin_panel":
        await admin_command(update, context)
    elif data == "toggle_auto":
        chat_id = update.effective_chat.id
        username = update.effective_user.username or update.effective_user.first_name
        user = get_user(chat_id)
        
        if not is_user_subscribed(chat_id):
            sub_txt = build_subscription_text()
            await query.message.edit_text(
                f"**SUBSCRIPTION REQUIRED!**\n\nAuto 3-Hour Injection feature only paid subscribers ke liye hai. Below subscription details dekhein:\n\n{sub_txt}",
                parse_mode="Markdown",
                reply_markup=get_back_button()
            )
            return

        current_state = user.get("auto_enabled", False)
        new_state = not current_state
        update_user(chat_id, {"auto_enabled": new_state})
        if new_state:
            schedule_user_automation(chat_id, context.application)
        else:
            stop_user_automation(chat_id)
        user = get_user(chat_id)
        dash_msg = build_dashboard_text(user, username, chat_id)
        reply_markup = get_dashboard_buttons(user, chat_id)
        await query.message.edit_text(dash_msg, parse_mode="Markdown", reply_markup=reply_markup)
    elif data == "change_country":
        if query and query.message:
            await query.message.reply_text("Default country code: 🇮🇳 India (+91). Use `/login` to sign in.")
    elif data == "start_login":
        await start_login_flow(update, context)
    elif data == "admin_broadcast_info":
        await query.message.reply_text("Admin Broadcast bhejney ke liye command enter karein:\n`/broadcast <your message text>`", parse_mode="Markdown")
    elif data == "admin_edit_usdt_info":
        await query.message.reply_text("USDT BEP-20 address set karne ke liye command enter karein:\n`/setusdt <BEP20_ADDRESS>`", parse_mode="Markdown")
    elif data == "admin_edit_uname_info":
        await query.message.reply_text("Admin support username set karne ke liye command enter karein:\n`/setsupport <@Username>`", parse_mode="Markdown")
    elif data == "admin_edit_rates_info":
        await query.message.reply_text("Subscription rate chart edit karne ke liye command enter karein:\n`/setrates <rate chart text>`", parse_mode="Markdown")
    elif data == "admin_grant_info":
        await query.message.reply_text("User ko manual subscription grant karne ke liye command enter karein:\n`/grant <USER_ID> <DAYS>`", parse_mode="Markdown")
    elif data == "admin_sub_list":
        users_db = get_all_users()
        sub_lines = []
        for cid_str, udata in users_db.items():
            uid = int(cid_str)
            if is_user_subscribed(uid):
                exp = udata.get("subscription_expiry", "Unlimited")
                un = udata.get("telegram_username", "Unknown")
                sub_lines.append(f"• `{uid}` (@{un}): Expires `{exp}`")
        
        list_txt = "\n".join(sub_lines) if sub_lines else "Koi active subscribed user nahi hai."
        await query.message.edit_text(
            f"**ACTIVE SUBSCRIBED USERS**\n═════════════════════════\n{list_txt}\n═════════════════════════",
            parse_mode="Markdown",
            reply_markup=get_back_button()
        )
    elif data.startswith("approve_pay_"):
        target_uid = int(data.split("_")[2])
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("15 Days ($3)", callback_data=f"grant_plan_{target_uid}_15"),
                InlineKeyboardButton("30 Days ($5)", callback_data=f"grant_plan_{target_uid}_30")
            ],
            [
                InlineKeyboardButton("45 Days ($7)", callback_data=f"grant_plan_{target_uid}_45")
            ]
        ])
        await query.message.edit_caption(
            caption=f"SELECT PLAN DURATION FOR USER `{target_uid}`:",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    elif data.startswith("grant_plan_"):
        parts = data.split("_")
        target_uid = int(parts[2])
        days = int(parts[3])

        expiry_str = grant_subscription(target_uid, days)
        user = get_user(target_uid)
        if user.get("connected"):
            schedule_user_automation(target_uid, context.application)

        await query.message.edit_caption(
            caption=f"PLAN ACTIVATED! User `{target_uid}` ko **{days} Days** ka plan add kar diya gaya hai. Expires: `{expiry_str}`.",
            parse_mode="Markdown"
        )

        settings = get_global_settings()
        admin_uname = settings.get("admin_username", "@ZenQuantSupport")
        user_notify = (
            "**SUBSCRIPTION ACTIVATED!**\n"
            "═════════════════════════\n"
            "Aapka payment approve ho gaya hai aur subscription plan active kar diya gaya hai!\n\n"
            f"• Plan Duration: `{days} Days`\n"
            f"• Expiry Date: `{expiry_str}`\n"
            f"• 3-Hour Auto Loop: `ENABLED`\n"
            "─────────────────────────\n"
            "*Bot ab har 3 ghante me automatic profit claim karega aur $50 re-inject karega!*\n"
            "═════════════════════════"
        )
        try:
            await context.bot.send_message(chat_id=target_uid, text=user_notify, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to notify user {target_uid}: {e}")
    elif data.startswith("reject_pay_"):
        target_uid = int(data.split("_")[2])
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Amount Not Received", callback_data=f"rej_r_{target_uid}_Amount not received in BEP-20 wallet"),
            ],
            [
                InlineKeyboardButton("Invalid Screenshot / TXID", callback_data=f"rej_r_{target_uid}_Invalid screenshot or fake TXID"),
            ],
            [
                InlineKeyboardButton("Wrong Network / Token", callback_data=f"rej_r_{target_uid}_Payment must be USDT on BEP-20 network")
            ]
        ])
        await query.message.edit_caption(
            caption=f"REJECT PAYMENT FOR USER `{target_uid}`\n\nSelect a preset reason below, OR type custom reason using:\n`/reject {target_uid} <your custom reason text>`",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    elif data.startswith("rej_r_"):
        parts = data.split("_", 3)
        target_uid = int(parts[2])
        reason = parts[3]

        await query.message.edit_caption(caption=f"Payment proof for user `{target_uid}` REJECTED.\nReason: {reason}", parse_mode="Markdown")
        
        settings = get_global_settings()
        admin_uname = settings.get("admin_username", "@ZenQuantSupport")
        reject_notify = (
            "**PAYMENT REJECTED**\n"
            "═════════════════════════\n"
            "Aapka payment screenshot reject ho gaya hai.\n\n"
            f"• **Reason**: {reason}\n"
            f"• Contact Admin: {admin_uname}\n"
            "═════════════════════════"
        )
        try:
            await context.bot.send_message(chat_id=target_uid, text=reject_notify, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to notify user {target_uid}: {e}")

# --- Post Initialization Hook ---

async def post_init(application):
    """Registers commands in Telegram UI [/] menu and restores background user automation."""
    menu_commands = [
        BotCommand("start", "Dashboard & main menu"),
        BotCommand("status", "Live balance & 3h countdown timer"),
        BotCommand("history", "Trade history (Bot vs Manual)"),
        BotCommand("inject", "Inject $50 trade order now"),
        BotCommand("claim", "Claim 3-hour yield reward"),
        BotCommand("buy", "Buy 3-Hour Auto-Inject plan"),
        BotCommand("orders", "List active trade order details"),
        BotCommand("injections", "Recent injection reports"),
        BotCommand("amount", "Set injection amount (Default: 50 USD)"),
        BotCommand("type", "Set plan (1: 3-Hour, 2: PLUS)"),
        BotCommand("auto", "Enable or disable 3-hour auto-loop"),
        BotCommand("admin", "Admin Control Panel (Admins Only)"),
        BotCommand("reject", "Reject payment with custom reason"),
        BotCommand("runnow", "Execute 1 full cycle immediately"),
        BotCommand("logs", "View recent activity log"),
        BotCommand("login", "Sign in with phone & password"),
        BotCommand("help", "Bot instructions & help")
    ]
    try:
        await application.bot.set_my_commands(menu_commands)
        logger.info("Registered Telegram UI Commands Menu successfully.")
    except Exception as e:
        logger.error(f"Failed to set Telegram UI commands menu: {e}")

    init_all_user_schedulers(application)
    logger.info("ZenQuant bot post-init completed. All user schedulers restored.")

# --- Main Bot Execution ---

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Login Conversation Handler
    login_handler = ConversationHandler(
        entry_points=[
            CommandHandler("login", start_login_flow),
            CommandHandler("register", start_login_flow),
            CallbackQueryHandler(start_login_flow, pattern="^start_login$")
        ],
        states={
            WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone)],
            WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)]
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
        per_message=False
    )

    app.add_handler(login_handler)
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("injections", injections_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("inject", inject_command))
    app.add_handler(CommandHandler("claim", claim_command))
    app.add_handler(CommandHandler("amount", amount_command))
    app.add_handler(CommandHandler("type", type_command))
    app.add_handler(CommandHandler("auto", auto_command))
    app.add_handler(CommandHandler("runnow", runnow_command))
    app.add_handler(CommandHandler("logs", logs_command))

    # Admin Commands
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("setusdt", setusdt_command))
    app.add_handler(CommandHandler("setsupport", setsupport_command))
    app.add_handler(CommandHandler("setrates", setrates_command))
    app.add_handler(CommandHandler("grant", grant_command))
    app.add_handler(CommandHandler("reject", reject_command))
    app.add_handler(CommandHandler("revoke", revoke_command))

    # Photo Payment Proof Handler
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    app.add_handler(CallbackQueryHandler(handle_callback))

    print("ZenQuant Auto-Bot running...")
    app.run_polling()

if __name__ == '__main__':
    main()
