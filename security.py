import base64
import hashlib
from config import FERNET_KEY

try:
    from cryptography.fernet import Fernet
    _cipher_suite = Fernet(FERNET_KEY)
    _USE_FERNET = True
except ImportError:
    _USE_FERNET = False

def _fallback_cipher(data: str, secret_key: bytes) -> str:
    key_hash = hashlib.sha256(secret_key).digest()
    data_bytes = data.encode('utf-8')
    enc = bytearray()
    for i, b in enumerate(data_bytes):
        enc.append(b ^ key_hash[i % len(key_hash)])
    return base64.b64encode(enc).decode('utf-8')

def _fallback_decipher(enc_str: str, secret_key: bytes) -> str:
    try:
        key_hash = hashlib.sha256(secret_key).digest()
        enc_bytes = base64.b64decode(enc_str)
        dec = bytearray()
        for i, b in enumerate(enc_bytes):
            dec.append(b ^ key_hash[i % len(key_hash)])
        return dec.decode('utf-8')
    except Exception:
        return ""

def encrypt_password(password: str) -> str:
    """Encrypts a plaintext password string."""
    if not password:
        return ""
    if _USE_FERNET:
        return _cipher_suite.encrypt(password.encode('utf-8')).decode('utf-8')
    return f"ENC_{_fallback_cipher(password, FERNET_KEY)}"

def decrypt_password(token: str) -> str:
    """Decrypts an encrypted password token."""
    if not token:
        return ""
    if token.startswith("ENC_"):
        return _fallback_decipher(token[4:], FERNET_KEY)
    if _USE_FERNET:
        try:
            return _cipher_suite.decrypt(token.encode('utf-8')).decode('utf-8')
        except Exception:
            return token
    return _fallback_decipher(token, FERNET_KEY)
