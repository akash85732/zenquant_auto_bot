import os
import base64

# Telegram Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN", "8882589954:AAH-_goqtr55mQMi8Wzv6nHFRnUuapRWhdc")

# Secret key for encrypting user passwords
KEY_FILE = os.path.join(os.path.dirname(__file__), ".secret.key")

if os.path.exists(KEY_FILE):
    with open(KEY_FILE, "rb") as f:
        FERNET_KEY = f.read()
else:
    FERNET_KEY = base64.urlsafe_b64encode(os.urandom(32))
    with open(KEY_FILE, "wb") as f:
        f.write(FERNET_KEY)

# Default Trading Configs
DEFAULT_TRADE_AMOUNT = 50  # USD
DEFAULT_TRADE_TYPE = "PLUS"  # "PLUS" or "3 HOUR"
DEFAULT_CYCLE_HOURS = 3
DEFAULT_COUNTRY_CODE = "+91"  # India
ZENQUANT_BASE_URL = "https://www.zenquantai.com"

# Admin Telegram Chat IDs
ADMIN_IDS = [8558893620, 5895803570]

