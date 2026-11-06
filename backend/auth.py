"""Telegram WebApp initData verification. No unverified client identity is trusted."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def verify_init_data(raw: str, bot_token: str, now: int | None = None) -> dict:
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError('Duplicate initData fields')
    data = dict(pairs)
    supplied = data.pop('hash', '')
    check = '\n'.join(f'{key}={value}' for key, value in sorted(data.items()))
    secret = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not supplied or not hmac.compare_digest(expected, supplied):
        raise ValueError('Invalid Telegram signature')
    timestamp = int(data.get('auth_date', '0'))
    age = (int(time.time()) if now is None else now) - timestamp
    if age < -30 or age > 3600:
        raise ValueError('Expired Telegram data')
    user = json.loads(data.get('user', '{}'))
    if type(user.get('id')) is not int or user['id'] <= 0:
        raise ValueError('Invalid Telegram user')
    return user
