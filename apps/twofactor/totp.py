import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

import qrcode
import qrcode.image.svg

STEP = 30
DIGITS = 6
ISSUER = "CashFlix"


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def code_at(secret, step):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def matching_step(secret, code, last_step=0, now=None):
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    current = int((now if now is not None else time.time()) // STEP)
    for step in (current - 1, current, current + 1):
        if step > last_step and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def uri(secret, email):
    label = quote(f"{ISSUER}:{email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={ISSUER}&digits={DIGITS}&period={STEP}"


def qr_svg(text):
    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, border=1)
    return image.to_string(encoding="unicode")


def spaced(secret):
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
