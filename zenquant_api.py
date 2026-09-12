import requests
import logging
import time
from typing import Tuple, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ZenQuantClient:
    def __init__(self, base_url: str = "https://data.zenquantai.com/api"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "language": "en",
            "Origin": "https://www.zenquantai.com",
            "Referer": "https://www.zenquantai.com/"
        })
        self.token: Optional[str] = None

    def set_token(self, token: str) -> None:
        """Sets the authorization bearer token."""
        self.token = token
        self.session.headers["Authorization"] = f"Bearer {token}"

    def login(self, account_or_email: str, password: str, country_code: str = "+91") -> Tuple[bool, str, Optional[str]]:
        """
        Authenticates with ZenQuant API.
        """
        login_url = f"{self.base_url}/login"
        clean_acc = account_or_email.strip().lstrip("+")
        clean_cc = country_code.strip().lstrip("+")
        if not clean_cc:
            clean_cc = "91"

        candidates = []
        if "@" in account_or_email:
            candidates.append({
                "email": account_or_email.strip(),
                "password": password,
                "type": "email",
                "phone": "",
                "phone_code": ""
            })
        else:
            candidates.append({
                "phone": clean_acc,
                "phone_code": clean_cc,
                "password": password,
                "type": "mobile",
                "email": ""
            })
            candidates.append({
                "phone": clean_acc,
                "phone_code": f"+{clean_cc}",
                "password": password,
                "type": "mobile",
                "email": ""
            })
            candidates.append({
                "email": clean_acc,
                "password": password
            })

        last_code = None
        last_msg = None

        for payload in candidates:
            try:
                res = self.session.post(login_url, json=payload, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    code = data.get("code")
                    last_code = code
                    last_msg = data.get("msg") or data.get("message")
                    
                    if code == 200 or data.get("success") is True:
                        token = data.get("data") or data.get("token") or data.get("accessToken")
                        if token:
                            self.set_token(token)
                            return True, "Login success!", token
                        return True, "Login success!", "active_session"
                    elif code in (1006, 1001):
                        continue
            except Exception as e:
                logger.error(f"Login error: {e}")

        if last_code == 1006:
            err_desc = "Galat phone number ya password hai. Please sahi details enter karein."
        elif last_code == 1001:
            err_desc = "Account format sahi nahi hai. Sahi 10-digit number enter karein."
        elif last_msg:
            err_desc = f"Login fail: {last_msg}"
        else:
            err_desc = "Network issue. Wapas try karein."

        return False, err_desc, None

    def get_account_status(self) -> Dict[str, Any]:
        """
        Fetches live balance, locked holdings, profit, and active deal countdown.
        """
        info_url = f"{self.base_url}/get_info"
        list_url = f"{self.base_url}/getDealList"
        
        avail_bal = 0.0
        locked_bal = 0.0
        total_profit = 0.0
        user_info = {}
        active_pos = None

        try:
            res_info = self.session.post(info_url, json={}, timeout=10)
            if res_info.status_code == 200:
                data = res_info.json()
                if data.get("code") == 200:
                    user_data = data.get("data", {})
                    user_info = user_data.get("userinfo", {})
                    avail_bal = float(user_info.get("balance") or user_info.get("available_balance") or 0.0)
                    locked_bal = float(user_info.get("freeze_balance") or 0.0)
                    total_profit = float(user_info.get("total_profit") or 0.0)
        except Exception as e:
            logger.error(f"Error fetching get_info: {e}")

        # Fetch active trade order and compute live countdown
        try:
            res_list = self.session.get(list_url, params={"page": 1, "size": 10, "type": 2}, timeout=10)
            if res_list.status_code == 200:
                data = res_list.json()
                if data.get("code") == 200:
                    orders = data.get("data", [])
                    active_orders = [o for o in orders if o.get("is_receive") == 0 or o.get("status") == 1]
                    if active_orders:
                        deal_order = active_orders[0]
                        elapsed_sec = int(deal_order.get("receive_times") or 0)
                        total_sec = 10800  # 3 Hours
                        rem_sec = max(0, total_sec - elapsed_sec)
                        
                        rem_h = rem_sec // 3600
                        rem_m = (rem_sec % 3600) // 60
                        rem_s = rem_sec % 60

                        if rem_sec > 0:
                            timer_formatted = f"{rem_h}h {rem_m}m {rem_s}s"
                        else:
                            timer_formatted = "0h 0m 0s (Claimable Now! 💰)"

                        active_pos = {
                            "order_id": deal_order.get("ordersn"),
                            "price": float(deal_order.get("price") or 50.0),
                            "start_time": deal_order.get("time"),
                            "elapsed_seconds": elapsed_sec,
                            "remaining_seconds": rem_sec,
                            "remaining_formatted": timer_formatted,
                            "deal_rate": float(deal_order.get("deal_rate") or 0.5),
                            "est_yield": round(float(deal_order.get("price") or 50.0) * 0.005, 4)
                        }
        except Exception as e:
            logger.error(f"Error fetching deal list: {e}")

        return {
            "available_balance": avail_bal,
            "total_holdings": locked_bal,
            "total_profit": total_profit,
            "user_info": user_info,
            "active_position": active_pos
        }

    def confirm_injection(self, amount: float = 50.0, trade_type: str = "PLUS") -> Tuple[bool, str, Dict[str, Any]]:
        """
        Submits injection order and waits 5-7 seconds to verify on server whether the trade order became active.
        """
        inject_url = f"{self.base_url}/createOrder"
        type_val = 1 if str(trade_type).upper() in ["1", "3 HOUR", "3HOUR"] else 2

        payload = {
            "type": type_val,
            "price": amount,
            "minuteIndex": 0,
            "is_new": 0
        }
        
        initial_ok = False
        initial_order_id = None
        server_msg = ""

        try:
            res = self.session.post(inject_url, json=payload, timeout=15)
            if res.status_code == 200:
                data = res.json()
                code = data.get("code")
                server_msg = data.get("msg") or ""
                if code == 200 or data.get("success") is True:
                    initial_ok = True
                    order_info = data.get("data", {})
                    if isinstance(order_info, dict):
                        initial_order_id = order_info.get("ordersn") or order_info.get("id")
        except Exception as e:
            logger.error(f"Injection submit error: {e}")

        # Wait 5 seconds for ZenQuant server to process and reflect the order
        time.sleep(5)

        # Verification check: Check live account status & deal list
        status = self.get_account_status()
        active_pos = status.get("active_position")
        locked_bal = status.get("total_holdings", 0.0)

        if active_pos or locked_bal > 0 or initial_ok:
            order_id = (active_pos.get("order_id") if active_pos else None) or initial_order_id or "ZQ-SUCCESS"
            return True, f"${amount:.2f} USD inject ho gaya hai!", {
                "order_id": order_id,
                "amount": amount,
                "trade_type": trade_type,
                "estimated_yield": round(amount * 0.005, 4),
                "duration": "3 Hours"
            }

        fail_reason = server_msg if server_msg else "Balance insufficient ya active trade in progress hai."
        return False, fail_reason, {}

    def claim_reward(self, order_id: Optional[str] = None) -> Tuple[bool, str, float]:
        """
        Claims matured order reward after 3-hour cycle.
        POST /receiveProfit
        """
        claim_url = f"{self.base_url}/receiveProfit"
        payload = {"ordersn": order_id} if order_id else {}

        try:
            res = self.session.post(claim_url, json=payload, timeout=15)
            if res.status_code == 200:
                data = res.json()
                code = data.get("code")
                if code == 200 or data.get("success") is True:
                    profit_earned = float(data.get("data", {}).get("profit") or data.get("profit") or 0.25)
                    return True, f"${profit_earned:.2f} reward claim ho gaya!", profit_earned
                else:
                    err_msg = data.get("msg") or "Reward abhi claimable nahi hai."
                    return False, err_msg, 0.0
            return False, f"Server HTTP error {res.status_code}", 0.0
        except Exception as e:
            logger.error(f"Claim error: {e}")
            return False, f"Claim error: {str(e)}", 0.0

    def get_deal_list(self, page: int = 1, size: int = 10, type_val: int = 2) -> list:
        """
        Fetches trade order history.
        GET /getDealList
        """
        url = f"{self.base_url}/getDealList"
        params = {"page": page, "size": size, "type": type_val}
        try:
            res = self.session.get(url, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("code") == 200:
                    return data.get("data", [])
        except Exception as e:
            logger.error(f"Error fetching deal list: {e}")
        return []
