from backend import bot
from backend.ai import parse_json_answer
from backend.db import Notification
from sqlalchemy import select
from .test_app import setup, signed, seed_feeding, admin_headers


def test_json_answer_accepts_exact_fence_only():
    assert parse_json_answer('```json\n{"decision":"REVIEW"}\n```') == {'decision': 'REVIEW'}
    assert parse_json_answer(' {"decision":"REVIEW"} ') == {'decision': 'REVIEW'}
    for raw in ('before {"decision":"REVIEW"}', '```python\n{}\n```', '[]'):
        try:
            parse_json_answer(raw)
        except ValueError:
            pass
        else:
            raise AssertionError('Accepted invalid provider answer')


def test_bot_replies_only_to_private_commands(monkeypatch):
    calls = []
    monkeypatch.setenv('APP_DOMAIN', 'catfeedik-test.tail16d0b1.ts.net')
    monkeypatch.setattr(bot, 'request', lambda _client, method, payload: calls.append((method, payload)))
    bot.handle(None, {'message': {'chat': {'type': 'group', 'id': 5}, 'text': '/start'}})
    bot.handle(None, {'message': {'chat': {'type': 'private', 'id': 7}, 'text': 'hello'}})
    assert calls == []
    bot.handle(None, {'message': {'chat': {'type': 'private', 'id': 7}, 'text': '/start'}})
    assert len(calls) == 1
    assert calls[0][0] == 'sendMessage'
    assert calls[0][1]['reply_markup']['inline_keyboard'][0][0]['web_app']['url'] == 'https://catfeedik-test.tail16d0b1.ts.net/'


def test_signed_avatar_and_in_app_approval_without_chat_notification(setup,monkeypatch):
    client,factory=setup
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test-bot-token')
    monkeypatch.setenv('APP_DOMAIN','catfeedik-test.tail16d0b1.ts.net')
    photo='https://t.me/i/userpic/320/telegram-test.jpg'
    signed_user={'id':81234,'first_name':'Аня','photo_url':photo}
    result=client.post('/api/auth/telegram',json={'init_data':signed(signed_user)})
    assert result.status_code==200
    headers={'Authorization':'Bearer '+result.json()['access_token']}
    assert result.json()['user']['photo_url']==photo
    user=result.json()['user']
    fid,_=seed_feeding(factory,user['id'])
    admin=admin_headers(client,factory,monkeypatch)
    assert client.post(f'/api/admin/feedings/{fid}/decision',headers=admin,
                       json={'decision':'APPROVED','reason':'Кормление подтверждено'}).status_code==200
    with factory() as db:
        assert db.scalar(select(Notification).where(Notification.feeding_id==fid)) is None
    assert client.get('/api/me/feedings',headers=headers).json()[0]['status']=='APPROVED'
    assert sum(item['delta'] for item in client.get('/api/me/points',headers=headers).json())==10


def test_telegram_photo_url_rejects_unsafe_schemes_and_credentials():
    from backend.auth import telegram_photo_url
    assert telegram_photo_url('https://user:password@evil.example/avatar.jpg')==''
    assert telegram_photo_url('http://t.me/i/userpic/320/a.jpg')==''


def test_in_app_rejection_without_chat_notification(setup,monkeypatch):
    client,factory=setup
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test-bot-token')
    monkeypatch.setenv('APP_DOMAIN','catfeedik-test.tail16d0b1.ts.net')
    user=client.post('/api/auth/telegram',json={'init_data':signed()}).json()['user']
    fid,_=seed_feeding(factory,user['id'])
    admin=admin_headers(client,factory,monkeypatch)
    assert client.post(f'/api/admin/feedings/{fid}/decision',headers=admin,
                       json={'decision':'REJECTED','reason':'Животное не ест'}).status_code==200
    with factory() as db:
        assert db.scalar(select(Notification).where(Notification.feeding_id==fid)) is None
    history=client.get('/api/me/feedings',headers={'Authorization':'Bearer '+client.post('/api/auth/telegram',json={'init_data':signed()}).json()['access_token']}).json()
    assert history[0]['status']=='REJECTED'
    assert history[0]['reason']=='Животное не ест'
