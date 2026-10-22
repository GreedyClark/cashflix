from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def fernet():
    if not settings.ENCRYPTION_KEY:
        raise ImproperlyConfigured("Add ENCRYPTION_KEY to .env")
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt(text):
    return fernet().encrypt(text.encode()).decode()


def decrypt(value):
    try:
        return fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return ""
