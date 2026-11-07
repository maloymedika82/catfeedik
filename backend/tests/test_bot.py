from backend import bot
from backend.ai import parse_json_answer


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
