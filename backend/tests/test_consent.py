from sqlalchemy import select,func
from .test_app import setup,login
from backend.db import ParticipationConsent
from backend.consent import VERSION,DOCUMENT_HASH


def raw_login(client):
    return {'Authorization':'Bearer '+client.post('/api/auth/dev').json()['access_token']}


def payload():return {'version':VERSION,'document_hash':DOCUMENT_HASH,'accepted':True}


def test_no_acceptance_is_assumed_and_upload_is_blocked(setup):
    client,factory=setup;headers=raw_login(client)
    assert client.get('/api/participation-terms').status_code==200
    assert client.get('/api/me/participation-consent').status_code==401
    assert client.get('/api/me/participation-consent',headers=headers).json()['accepted'] is False
    response=client.post('/api/feedings',headers=headers,json=dict(request_key='consent-test-123456',city='ignored',latitude=55.75,longitude=37.61,accuracy=10,mime_type='video/mp4',size=10))
    assert response.status_code==409
    with factory() as db:assert db.scalar(select(func.count()).select_from(ParticipationConsent))==0


def test_explicit_acceptance_survives_new_session_and_replay(setup):
    client,factory=setup;headers=raw_login(client)
    first=client.post('/api/me/participation-consent',headers=headers,json=payload())
    assert first.status_code==200 and first.json()['accepted']
    again=client.post('/api/me/participation-consent',headers=headers,json=payload())
    assert again.json()['accepted_at']==first.json()['accepted_at']
    new_headers=raw_login(client)
    assert client.get('/api/me/participation-consent',headers=new_headers).json()['accepted']
    with factory() as db:assert db.scalar(select(func.count()).select_from(ParticipationConsent))==1


def test_outdated_or_unchecked_terms_cannot_be_accepted(setup):
    client,_=setup;headers=raw_login(client)
    for change,status in [({'accepted':False},422),({'accepted':'true'},422),({'version':'old'},409),({'document_hash':'0'*64},409)]:
        assert client.post('/api/me/participation-consent',headers=headers,json=payload()|change).status_code==status
    assert not client.get('/api/me/participation-consent',headers=headers).json()['accepted']


def test_changed_document_requires_fresh_acceptance(setup):
    client,factory=setup;headers=login(client)
    with factory() as db:
        row=db.scalar(select(ParticipationConsent));row.document_hash='0'*64;db.commit()
    assert not client.get('/api/me/participation-consent',headers=headers).json()['accepted']
    assert client.post('/api/me/participation-consent',headers=headers,json=payload()).json()['accepted']


def test_pending_legacy_upload_requires_current_consent(setup):
    from sqlalchemy import delete
    from .test_app import create_upload
    client,factory=setup;headers=login(client);item=create_upload(client,headers)
    with factory() as db:db.execute(delete(ParticipationConsent));db.commit()
    assert client.put('/api'+item['upload_path'],headers={**headers,'Content-Type':'video/mp4'},content=b'0123456789').status_code==409
    assert client.post('/api/feedings/'+item['id']+'/complete',headers=headers).status_code==409


def test_consent_is_bound_to_authenticated_account(setup,monkeypatch):
    from .test_app import signed
    client,_=setup;first=login(client)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test-bot-token')
    result=client.post('/api/auth/telegram',json={'init_data':signed({'id':77777,'first_name':'Other participant'})}).json()
    second={'Authorization':'Bearer '+result['access_token']}
    assert not client.get('/api/me/participation-consent',headers=second).json()['accepted']
    assert client.post('/api/me/participation-consent',headers=second,json=payload()|{'user_id':'other'}).status_code==422
    assert client.get('/api/me/participation-consent',headers=first).json()['accepted']


def test_frozen_account_cannot_accept(setup):
    from backend.db import User
    client,factory=setup;headers=raw_login(client)
    with factory() as db:
        participant=db.scalar(select(User));participant.frozen=True;db.commit()
    assert client.post('/api/me/participation-consent',headers=headers,json=payload()).status_code==403
