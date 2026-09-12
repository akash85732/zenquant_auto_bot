# 🤖 ZenQuant Auto-Bot

Automated trading, claim management, and 3-hour recurring yield cycle bot for ZenQuant (`zenquantai.com`).

---

## ⚡ Key Features

- 🔐 **Fernet Encrypted Login**: Securely encrypts user phone numbers & passwords using AES-256.
- 💉 **Automated $50 Injection**: Automatically injects funds into the **PLUS** (0.5% ROI) or **3 HOUR** plan.
- 💰 **Auto-Claim Rewards**: Monitors 3-hour timer, claims matured yields (~$0.20 - $0.25 per cycle), and returns principal to available balance.
- 🔄 **Background Recurring Scheduler**: Runs every 3 hours for every registered user automatically.
- 📊 **Dashboard & Interactive UI**: Real-time status reporting with Telegram Inline Keyboard buttons.

---

## 🚀 Installation & Running

### 1. Set Telegram Bot Token
Edit `config.py` or export `BOT_TOKEN`:
```bash
export BOT_TOKEN="your_telegram_bot_token_here"
```

### 2. Run Bot
```bash
cd /data/data/com.termux/files/home/zenquant_auto_bot
python3 bot.py
```

---

## 🛠️ Bot Commands

- `/start` - Launch Dashboard & interactive menu buttons
- `/register` - Connect phone number & password
- `/status` - Check current balance, active holdings, and timer
- `/orders` - View active order IDs
- `/inject` - Immediately place $50 injection order
- `/claim` - Claim finished 3-hour yield
- `/amount <usd>` - Change injection amount (default: 50 USD)
- `/type <1|2>` - Switch plan (`1`: 3 HOUR, `2`: PLUS)
- `/auto <on|off>` - Enable/disable 3-hour background automation
- `/runnow` - Trigger 1 full cycle immediately
- `/logs` - View recent activity log
