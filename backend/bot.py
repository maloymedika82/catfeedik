"""Minimal private-chat entry point for the Catfeedik Mini App."""
import os
from pathlib import Path
import sys
import time

import httpx
from sqlalchemy import or_, select
from .db import SessionLocal, Notification, User, Feeding


STATE = Path('/data/bot/offset')
WELCOME = (
    'Привет! Здесь можно показать, как ты кормишь кошку или собаку.\n\n'
    'Открой приложение, сними короткое видео и отправь его на проверку. '
    'После подтверждения кормления появятся поинты.'
)
HELP = (
    'Нажми «Открыть Catfeedik» и разреши доступ к камере и геолокации. '
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
        'short_description': 'Корми кошек и собак, снимай видео и получай поинты после проверки.'})
    request(client, 'setMyDescription', {
        'description': 'Catfeedik помогает отмечать кормления кошек и собак. Сними короткое видео в приложении и отправь его на проверку. Подтверждённые кормления появятся на карте, а в профиле начислятся поинты. Денежных выплат нет.'})
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


def notification_text(kind, feeding):
    city=feeding.city if feeding else 'вашем городе'
    if kind=='APPROVED':
        return f'Кормление в городе {city} подтверждено. Поинты начислены; подробности и видео — в профиле Catfeedik.'
    if kind=='REJECTED':
        reason=(feeding.decision_reason if feeding else '').strip()[:700]
        return f'Видео кормления в городе {city} отклонено. {reason}\nЕсли не согласны, подайте апелляцию в профиле Catfeedik.'
    return f'Видео кормления в городе {city} передано на ручную проверку. Статус можно посмотреть в профиле Catfeedik.'


def deliver_notifications(client, factory=SessionLocal, now=None):
    now=int(time.time()) if now is None else now
    delivered=0
    for _ in range(20):
        with factory() as db:
            item=db.scalar(select(Notification).where(
                or_((Notification.status=='PENDING') & (Notification.next_attempt_at<=now),
                    (Notification.status=='SENDING') & (Notification.claimed_at<=now-120)))
                .order_by(Notification.created_at,Notification.id).limit(1).with_for_update(skip_locked=True))
            if not item:break
            item.status='SENDING';item.claimed_at=now
            notification_id=item.id;kind=item.kind
            user=db.get(User,item.user_id);feeding=db.get(Feeding,item.feeding_id)
            if not user or user.telegram_id<=0 or not user.notify_enabled:
                item.status='SKIPPED';db.commit();continue
            chat_id=user.telegram_id;text=notification_text(kind,feeding)
            db.commit()
        try:
            request(client,'sendMessage',{'chat_id':chat_id,'text':text,'reply_markup':{'inline_keyboard':[[
                {'text':'Открыть Catfeedik','web_app':{'url':app_url()}}]]}})
        except RuntimeError:
            with factory() as db:
                item=db.get(Notification,notification_id)
                if item and item.status=='SENDING':
                    item.attempts+=1
                    item.status='FAILED' if item.attempts>=8 else 'PENDING'
                    item.next_attempt_at=now+min(3600,30*2**min(item.attempts,7))
                    db.commit()
        else:
            with factory() as db:
                item=db.get(Notification,notification_id)
                if item and item.status=='SENDING':
                    item.status='SENT';item.sent_at=now;db.commit();delivered+=1
    return delivered


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
                deliver_notifications(client)
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
