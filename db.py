import json
import os
import datetime
from typing import Dict, Any, Optional, List
from config import ADMIN_IDS

DB_FILE = os.path.join(os.path.dirname(__file__), "users_db.json")
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

def load_db() -> Dict[str, Any]:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_db(data: Dict[str, Any]) -> None:
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_global_settings() -> Dict[str, Any]:
    default_settings = {
        "usdt_bep20_address": "0x7a39F999812A2789123048991212889218291283",
        "admin_username": "@Piyux32",
        "subscription_rates": "• 15 Days Plan: $3 USD\n• 30 Days Plan: $5 USD\n• 45 Days Plan: $7 USD"
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_settings.update(saved)
        except Exception:
            pass
    return default_settings

def update_global_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    settings = get_global_settings()
    settings.update(updates)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    return settings

def get_user(chat_id: int) -> Dict[str, Any]:
    db = load_db()
    cid_str = str(chat_id)
    if cid_str not in db:
        db[cid_str] = {
            "telegram_username": "",
            "phone": "",
            "encrypted_password": "",
            "country_code": "+91",
            "connected": False,
            "trade_amount": 50,
            "trade_type": "PLUS",  # "PLUS" or "3 HOUR"
            "auto_enabled": False,
            "runtime_mode": "LIVE",
            "last_order_id": None,
            "bot_order_ids": [],
            "active_orders": [],
            "subscription_expiry": None,
            "logs": []
        }
        save_db(db)
    user_obj = db[cid_str]
    if "bot_order_ids" not in user_obj:
        user_obj["bot_order_ids"] = []
    if "subscription_expiry" not in user_obj:
        user_obj["subscription_expiry"] = None
    return user_obj

def update_user(chat_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
    db = load_db()
    cid_str = str(chat_id)
    user_data = get_user(chat_id)
    user_data.update(updates)
    db[cid_str] = user_data
    save_db(db)
    return user_data

def get_all_users() -> Dict[str, Any]:
    return load_db()

def find_user_by_query(query: str) -> Optional[int]:
    clean_q = query.strip().lstrip("@").lower()
    if not clean_q:
        return None

    users_db = get_all_users()
    
    # 1. Exact numeric Telegram Chat ID
    if clean_q.isdigit():
        uid = int(clean_q)
        if str(uid) in users_db:
            return uid
            
    # 2. Exact match on username or phone
    for cid_str, udata in users_db.items():
        uname = str(udata.get("telegram_username", "")).lstrip("@").lower()
        phone = str(udata.get("phone", "")).lower()
        if clean_q == uname or clean_q == phone:
            return int(cid_str)
            
    # 3. Partial match on username
    for cid_str, udata in users_db.items():
        uname = str(udata.get("telegram_username", "")).lstrip("@").lower()
        if clean_q in uname and len(clean_q) >= 3:
            return int(cid_str)

    return None


def is_user_subscribed(chat_id: int) -> bool:
    if chat_id in ADMIN_IDS:
        return True
    user = get_user(chat_id)
    expiry_str = user.get("subscription_expiry")
    if not expiry_str:
        return False
    try:
        expiry_dt = datetime.datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
        return expiry_dt > datetime.datetime.now()
    except Exception:
        return False

def grant_subscription(chat_id: int, days: int) -> str:
    user = get_user(chat_id)
    now = datetime.datetime.now()
    current_expiry_str = user.get("subscription_expiry")
    
    start_dt = now
    if current_expiry_str:
        try:
            curr_dt = datetime.datetime.strptime(current_expiry_str, "%Y-%m-%d %H:%M:%S")
            if curr_dt > now:
                start_dt = curr_dt
        except Exception:
            start_dt = now

    new_expiry = start_dt + datetime.timedelta(days=days)
    new_expiry_str = new_expiry.strftime("%Y-%m-%d %H:%M:%S")
    update_user(chat_id, {
        "subscription_expiry": new_expiry_str,
        "auto_enabled": True
    })
    add_user_log(chat_id, f"⭐ Subscription granted/extended for {days} days. Expires: {new_expiry_str}")
    return new_expiry_str

def revoke_subscription(chat_id: int) -> None:
    update_user(chat_id, {
        "subscription_expiry": None,
        "auto_enabled": False
    })
    add_user_log(chat_id, "⏸️ Subscription revoked/expired.")

def record_bot_order(chat_id: int, order_id: str) -> None:
    user = get_user(chat_id)
    bot_orders = user.get("bot_order_ids", [])
    if order_id and order_id not in bot_orders:
        bot_orders.append(order_id)
        if len(bot_orders) > 50:
            bot_orders = bot_orders[-50:]
        update_user(chat_id, {"bot_order_ids": bot_orders})

def add_user_log(chat_id: int, message: str) -> None:
    user = get_user(chat_id)
    logs = user.get("logs", [])
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logs.append(f"[{timestamp}] {message}")
    if len(logs) > 50:
        logs = logs[-50:]  # Keep last 50 logs
    update_user(chat_id, {"logs": logs})

