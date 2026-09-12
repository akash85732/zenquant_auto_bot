import time
import logging
import threading
import asyncio
from datetime import datetime, timedelta
from db import get_user, update_user, add_user_log, load_db, record_bot_order, is_user_subscribed

logger = logging.getLogger(__name__)

# Active background threads dictionary {chat_id: threading.Thread}
_active_threads = {}
_thread_stop_flags = {}

def send_telegram_msg_sync(bot_app, chat_id: int, text: str, parse_mode: str = "Markdown"):
    """
    Safely sends an async Telegram message from a synchronous background thread.
    """
    if not bot_app or not hasattr(bot_app, "bot"):
        return

    try:
        loop = None
        try:
            loop = bot_app.loop
        except AttributeError:
            pass

        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                bot_app.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode),
                loop
            )
        else:
            asyncio.run(bot_app.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode))
    except Exception as e:
        logger.error(f"Error sending background telegram message to {chat_id}: {e}")

def execute_3h_auto_cycle(chat_id: int, bot_app=None):
    """
    Automated cycle executed every 3 hours:
    1. Verify active paid subscription.
    2. Log in to ZenQuant using stored credentials.
    3. Claim finished order reward / yield.
    4. Re-inject configured trade amount into PLUS/3HOUR plan.
    5. Send full Telegram status report & notification to user.
    """
    user = get_user(chat_id)
    if not user.get("auto_enabled"):
        logger.info(f"Automation disabled for user {chat_id}, skipping job.")
        return

    # Check subscription validity
    if not is_user_subscribed(chat_id):
        logger.info(f"Subscription expired for user {chat_id}, stopping auto cycle.")
        stop_user_automation(chat_id)
        update_user(chat_id, {"auto_enabled": False})
        expire_msg = (
            "⚠️ **SUBSCRIPTION EXPIRED!**\n"
            "═════════════════════════\n"
            "Aapka 3-Hour Auto-Inject plan finish ho gaya hai.\n"
            "Auto-loop pause kar diya gaya hai.\n\n"
            "💳 *Renewal ke liye **💳 Buy Subscription** button click karke plan select karein.*"
        )
        send_telegram_msg_sync(bot_app, chat_id, expire_msg)
        return

    phone = user.get("phone")
    encrypted_pwd = user.get("encrypted_password")
    country_code = user.get("country_code", "+91")
    password = decrypt_password(encrypted_pwd) if encrypted_pwd else ""
    amount = user.get("trade_amount", 50)
    trade_type = user.get("trade_type", "PLUS")

    if not phone or not password:
        add_user_log(chat_id, "Auto-cycle skipped: Missing account credentials.")
        return

    client = ZenQuantClient()
    auth_ok, msg, token = client.login(phone, password, country_code)
    if not auth_ok:
        add_user_log(chat_id, f"Auto-cycle login failed: {msg}")
        fail_msg = f"❌ **Auto-Cycle Failed**\nLogin failed for account `{phone}`: {msg}\nPlease re-authenticate using `/login`."
        send_telegram_msg_sync(bot_app, chat_id, fail_msg)
        return

    # Step 1: Claim matured order if any
    last_order_id = user.get("last_order_id")
    claim_ok, claim_msg, reward = client.claim_reward(last_order_id)
    add_user_log(chat_id, f"💰 [AUTO CLAIM] {claim_msg}")

    # Step 2: Re-inject $50 into configured plan
    inj_ok, inj_msg, order_data = client.confirm_injection(amount, trade_type)
    new_order_id = order_data.get("order_id", "ZQ-LIVE")
    
    # Record bot injection ID for Manual vs Bot tracking
    if inj_ok and new_order_id:
        record_bot_order(chat_id, new_order_id)
        add_user_log(chat_id, f"🤖 [BOT AUTO-INJECT] Injected ${amount:.2f} into {trade_type} (Order: {new_order_id})")
    else:
        add_user_log(chat_id, f"🤖 [BOT AUTO-INJECT ERROR] {inj_msg}")

    next_run = datetime.now() + timedelta(hours=3)

    update_user(chat_id, {
        "last_order_id": new_order_id,
        "last_cycle_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

    # Step 3: Fetch updated status & Send Telegram Notification
    status_info = client.get_account_status()
    avail_bal = status_info.get("available_balance", 0.0)

    status_icon = "✅" if inj_ok else "⚠️"
    report_text = (
        "🤖 **AUTOMATED 3-HOUR BOT CYCLE COMPLETE**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Claim Status**: {claim_msg}\n"
        f"💉 **Injection Type**: `🤖 BOT AUTO-INJECT`\n"
        f"🎯 **Trade Plan**: `{trade_type}`\n"
        f"🆔 **New Order ID**: `{new_order_id}`\n"
        f"💵 **Available Balance**: `${avail_bal:.2f} USD`\n"
        f"⏱️ **Next Auto-Cycle**: `{next_run.strftime('%I:%M:%S %p')}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{status_icon} *Capital re-locked for 3 hours.*"
    )
    send_telegram_msg_sync(bot_app, chat_id, report_text)

def _auto_loop_worker(chat_id: int, bot_app=None):
    """Background worker thread running 3-hour recurring loop."""
    logger.info(f"Started 3-hour background loop worker for user {chat_id}")
    while not _thread_stop_flags.get(chat_id, False):
        for _ in range(10800):
            if _thread_stop_flags.get(chat_id, False):
                logger.info(f"Stop flag detected for user {chat_id}, exiting thread.")
                return
            time.sleep(1)
            
        try:
            execute_3h_auto_cycle(chat_id, bot_app)
        except Exception as e:
            logger.error(f"Error in auto cycle worker for user {chat_id}: {e}")

def schedule_user_automation(chat_id: int, bot_app=None):
    """Schedules a 3-hour recurring thread for a user."""
    stop_user_automation(chat_id)
    _thread_stop_flags[chat_id] = False
    thread = threading.Thread(target=_auto_loop_worker, args=(chat_id, bot_app), daemon=True)
    _active_threads[chat_id] = thread
    thread.start()
    logger.info(f"Scheduled 3-hour auto thread for user {chat_id}")

def stop_user_automation(chat_id: int):
    """Stops background automation thread for a user."""
    _thread_stop_flags[chat_id] = True
    if chat_id in _active_threads:
        del _active_threads[chat_id]
        logger.info(f"Stopped automation thread for user {chat_id}")

def init_all_user_schedulers(bot_app=None):
    """Restores background 3-hour automation threads for all registered users upon bot startup."""
    db = load_db()
    restored_count = 0
    for cid_str, user_data in db.items():
        try:
            chat_id = int(cid_str)
            if user_data.get("auto_enabled") and user_data.get("connected"):
                if is_user_subscribed(chat_id):
                    schedule_user_automation(chat_id, bot_app)
                    restored_count += 1
                else:
                    update_user(chat_id, {"auto_enabled": False})
        except ValueError:
            pass
    logger.info(f"Restored {restored_count} user automation threads on bot startup.")

