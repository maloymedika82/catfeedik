"""Minimal private-chat entry point for the Catfeedik Mini App."""
import os
from pathlib import Path
import sys
import time

import httpx


STATE = Path('/data/bot/offset')
WELCOME = (
    'Привет! Здесь можно снять кормление кошки или собаки и отправить видео на проверку.\n\n'
    'За подтверждённые кормления начисляются поинты.\n\n'
    'Нажми «Открыть Catfeedik» — покажем, как всё работает.'
)
HELP = (
    'Нажми «Открыть Catfeedik», выбери город и разреши доступ к камере и микрофону. '
    'Сними кормление одним видео до 15 секунд. Статус будет в профиле приложения.\n\n'
    'Если запись не получается, проверь разрешения Telegram в настройках телефона.'
)


def app_url():
    domain = (os.getenv('APP_DOMAIN') or '').strip()
    if not domain or '/' in domain or ':' in domain:
        raise RuntimeError('APP_DOMAIN must be a hostname')
    return 'https://' + domain + '/'


def request(client, method, payload=None):
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise RuntimeError('TELEGRAM_BOT_TOKEN is missing')
    try:
        response = client.post('https://api.telegram.org/bot' + token + '/' + method, json=payload or {})
        response.raise_for_status()
        result = response.json()
        if not result.get('ok'):
            raise RuntimeError('Telegram rejected ' + method)
        return result['result']
    except (httpx.HTTPError, ValueError, KeyError):
        # Telegram error bodies may contain sensitive request data.
        raise RuntimeError('Telegram request failed: ' + method) from None


def configure(client):
    username = request(client, 'getMe').get('username', '').lower()
    if username != (os.getenv('TELEGRAM_BOT_USERNAME') or 'animalfeedikbot').lower():
        raise RuntimeError('Bot token belongs to a different bot')
    request(client, 'setMyName', {'name': 'Catfeedik'})
    request(client, 'setMyShortDescription', {
        'short_description': 'Снимай кормления кошек и собак, отправляй видео на проверку и следи за своим вкладом.'})
    request(client, 'setMyDescription', {
        'description': 'Сними кормление кошки или собаки одним видео до 15 секунд со звуком. Отправь ролик на проверку и следи за статусом в профиле. За подтверждённые кормления начисляются поинты — показатель твоего вклада, без денежных выплат.'})
    request(client, 'setMyCommands', {'commands': [
        {'command': 'start', 'description': 'Открыть приложение'},
        {'command': 'help', 'description': 'Как снять и отправить видео'},
    ]})
    request(client, 'setChatMenuButton', {'menu_button': {
        'type': 'web_app', 'text': 'Открыть Catfeedik', 'web_app': {'url': app_url()}}})


def handle(client, update):
    message = update.get('message') or {}
    chat = message.get('chat') or {}
    if chat.get('type') != 'private':
        return
    command = (message.get('text') or '').split(' ', 1)[0].split('@', 1)[0].lower()
    if command not in ('/start', '/help'):
        return
    request(client, 'sendMessage', {
        'chat_id': chat['id'], 'text': WELCOME if command == '/start' else HELP,
        'reply_markup': {'inline_keyboard': [[{
            'text': 'Открыть Catfeedik', 'web_app': {'url': app_url()},
        }]]},
    })


def save_offset(value):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(str(value), encoding='ascii')
    temporary.replace(STATE)


def run():
    app_url()
    with httpx.Client(timeout=40, follow_redirects=False) as client:
        if request(client, 'getWebhookInfo').get('url'):
            raise RuntimeError('A Telegram webhook is already configured')
        if STATE.exists():
            offset = int(STATE.read_text(encoding='ascii'))
        else:
            # Skip stale messages that arrived before this service was enabled.
            recent = request(client, 'getUpdates', {'offset': -1, 'limit': 1, 'timeout': 0, 'allowed_updates': ['message']})
            offset = recent[-1]['update_id'] + 1 if recent else 0
            save_offset(offset)
        while True:
            try:
                updates = request(client, 'getUpdates', {
                    'offset': offset, 'timeout': 25, 'allowed_updates': ['message']})
                for update in updates:
                    handle(client, update)
                    offset = update['update_id'] + 1
                    save_offset(offset)
            except RuntimeError:
                print('Telegram polling error; retrying', file=sys.stderr, flush=True)
                time.sleep(5)


if __name__ == '__main__':
    with httpx.Client(timeout=30, follow_redirects=False) as telegram:
        if '--configure' in sys.argv:
            configure(telegram)
            print('Bot profile, commands and menu button configured.')
        else:
            run()
