import json
import os
from pathlib import Path
import shutil
import subprocess
import httpx
import pytest
from sqlalchemy import select
from backend.db import Feeding,VideoAsset,Points,AICheck,User
from backend.local_storage import object_path
from backend.processing import process_video
from backend.ai import Verdict,moderate,ProviderUnavailable
from backend.geography import nearest_city
from .test_app import setup,login,create_upload,signed

@pytest.fixture(scope='session')
def real_video(tmp_path_factory):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg/FFprobe required for actual media tests')
    path=tmp_path_factory.mktemp('media')/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=30',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','1.2','-c:v','libx264','-pix_fmt','yuv420p',
        '-c:a','aac','-metadata','location=+55.0000+037.0000/',str(path)],check=True)
    return path.read_bytes()


def upload_video(client,headers,data,key='processing-video-12345'):
    item=create_upload(client,headers,size=len(data),key=key)
    result=client.put('/api'+item['upload_path'],headers={**headers,'Content-Type':'video/mp4'},content=data)
    assert result.status_code==204,result.text
    result=client.post(f"/api/feedings/{item['id']}/complete",headers=headers)
    assert result.status_code==200 and result.json()['status']=='PROCESSING'
    return item['id']


def verdict(decision='APPROVE',confidence=.99):
    return Verdict(decision=decision,confidence=confidence,reason='Результат тестовой модели',
        animal_visible=decision!='REJECT',food_visible=decision!='REJECT',eating_visible=decision!='REJECT',suspicious=False)


def test_real_ffmpeg_processing_without_ai_requires_review(setup,real_video,monkeypatch):
    client,factory=setup;headers=login(client)
    monkeypatch.delenv('AI_API_KEY',raising=False)
    fid=upload_video(client,headers,real_video)
    assert client.get(f'/api/public/videos/{fid}').status_code==404
    result=process_video(fid,factory)
    assert result=={'status':'READY','feeding_status':'REVIEW'}
    with factory() as db:
        asset=db.get(VideoAsset,fid)
        assert 0<asset.duration<=15
        assert object_path(asset.output_key).is_file() and object_path(asset.poster_key).is_file()
        metadata=json.loads(subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(object_path(asset.output_key))],capture_output=True,check=True).stdout)
        video=next(s for s in metadata['streams'] if s['codec_type']=='video')
        assert video['codec_name']=='h264' and video['r_frame_rate']=='30/1'
        assert any(s['codec_name']=='aac' for s in metadata['streams'])
        assert 'location' not in metadata['format'].get('tags',{})
        assert db.get(AICheck,fid).status=='NOT_CONFIGURED'
    assert client.get('/api/me',headers=headers).json()['points']==0
    assert process_video(fid,factory)=={'status':'unchanged'}


def test_ai_approval_server_award_public_feed_and_likes(setup,real_video,monkeypatch):
    client,factory=setup;headers=login(client)
    monkeypatch.setattr('backend.processing.configured',lambda:True)
    monkeypatch.setattr('backend.processing.moderate',lambda frames:verdict())
    fid=upload_video(client,headers,real_video)
    assert process_video(fid,factory)['feeding_status']=='APPROVED'
    assert client.get('/api/me',headers=headers).json()['points']==10
    process_video(fid,factory)
    assert client.get('/api/me',headers=headers).json()['points']==10
    cities=client.get('/api/cities').json()
    assert len(cities)==1 and cities[0]['feedings']==1
    assert (cities[0]['latitude'],cities[0]['longitude'])!=(55,37)
    feed=client.get('/api/feed',params={'city_id':cities[0]['id']}).json()
    assert len(feed['items'])==1 and 'latitude' not in feed['items'][0] and 'longitude' not in feed['items'][0]
    public=client.get(feed['items'][0]['video_url'],headers={'Range':'bytes=0-15'})
    assert public.status_code==206 and len(public.content)==16
    assert client.get(feed['items'][0]['poster_url']).headers['content-type']=='image/jpeg'
    for _ in range(2):
        assert client.put(f'/api/feedings/{fid}/like',headers=headers).json()['likes']==1
    assert client.get('/api/me/likes',headers=headers).json()==[fid]
    for _ in range(2):assert client.delete(f'/api/feedings/{fid}/like',headers=headers).json()['likes']==0


def test_identical_video_other_user_is_review_not_reward(setup,real_video,monkeypatch):
    client,factory=setup;headers=login(client);calls=[]
    monkeypatch.setattr('backend.processing.configured',lambda:True)
    monkeypatch.setattr('backend.processing.moderate',lambda frames:(calls.append(True) or verdict()))
    fid=upload_video(client,headers,real_video)
    assert process_video(fid,factory)['feeding_status']=='APPROVED'
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test-bot-token')
    other=client.post('/api/auth/telegram',json={'init_data':signed({'id':12345,'first_name':'Other'})}).json()
    other_headers={'Authorization':'Bearer '+other['access_token']}
    terms=client.get('/api/me/participation-consent',headers=other_headers).json()
    assert client.post('/api/me/participation-consent',headers=other_headers,json={k:terms[k] for k in ('version','document_hash')}|{'accepted':True}).status_code==200
    second=upload_video(client,other_headers,real_video,key='duplicate-video-12345')
    assert process_video(second,factory)['feeding_status']=='REVIEW'
    assert len(calls)==1
    with factory() as db:
        assert 'DUPLICATE_UPLOAD' in db.get(VideoAsset,second).flags
    assert client.get('/api/me',headers=other_headers).json()['points']==0


def test_invalid_video_never_public_and_cannot_award(setup):
    client,factory=setup;headers=login(client)
    fid=upload_video(client,headers,b'not a video')
    assert process_video(fid,factory)['status']=='INVALID'
    with factory() as db:
        assert db.get(Feeding,fid).status=='REVIEW'
        assert db.get(VideoAsset,fid).status=='INVALID'
    assert client.get(f'/api/public/videos/{fid}').status_code==404
    assert client.get('/api/me',headers=headers).json()['points']==0


def test_ai_technical_error_goes_review(setup,real_video,monkeypatch):
    client,factory=setup;headers=login(client)
    monkeypatch.setattr('backend.processing.configured',lambda:True)
    def unavailable(_):raise ProviderUnavailable('Unreachable')
    monkeypatch.setattr('backend.processing.moderate',unavailable)
    fid=upload_video(client,headers,real_video)
    assert process_video(fid,factory)['feeding_status']=='REVIEW'
    with factory() as db:assert db.get(AICheck,fid).status=='ERROR'
    assert client.get('/api/me',headers=headers).json()['points']==0


def test_ai_rejection_has_no_points(setup,real_video,monkeypatch):
    client,factory=setup;headers=login(client)
    monkeypatch.setattr('backend.processing.configured',lambda:True)
    monkeypatch.setattr('backend.processing.moderate',lambda frames:verdict('REJECT'))
    fid=upload_video(client,headers,real_video)
    assert process_video(fid,factory)['feeding_status']=='REJECTED'
    assert client.get('/api/me',headers=headers).json()['points']==0


def test_geography_worldwide_and_antimeridian():
    moscow=nearest_city(55.75,37.61);new_york=nearest_city(40.71,-74.0);tokyo=nearest_city(35.68,139.69)
    assert moscow['country']=='RU' and new_york['country']=='US' and tokyo['country']=='JP'
    assert nearest_city(-16,179.9)['country'] in ('FJ','TO','WS')


def test_vision_adapter_discovery_validates_and_sends_no_location(tmp_path,monkeypatch):
    monkeypatch.setenv('AI_API_KEY','unit-test-key-only');monkeypatch.setenv('AI_MODEL','auto')
    image=tmp_path/'frame.jpg';image.write_bytes(b'jpeg-test')
    requests=[]
    def handler(request):
        requests.append(request)
        if request.url.path.endswith('/models'):
            return httpx.Response(200,json={'data':[{'id':'provider/gemini-flash-lite'}]})
        payload=json.loads(request.content)
        assert payload['model']=='provider/gemini-flash-lite'
        assert 'latitude' not in request.content.decode() and 'longitude' not in request.content.decode()
        return httpx.Response(200,json={'choices':[{'message':{'content':verdict().model_dump_json()}}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result=moderate([image],client)
    assert result.decision=='APPROVE' and result.provider_model=='provider/gemini-flash-lite'
    assert len(requests)==2


def test_vision_adapter_downgrades_unjustified_approval(tmp_path,monkeypatch):
    monkeypatch.setenv('AI_API_KEY','unit-test-only');monkeypatch.setenv('AI_MODEL','provider-test')
    image=tmp_path/'frame.jpg';image.write_bytes(b'test')
    response=verdict();response.eating_visible=False
    with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'choices':[{'message':{'content':response.model_dump_json()}}]}))) as client:
        assert moderate([image],client).decision=='REVIEW'


def test_video_limit_development_defaults_production_closed(setup,monkeypatch):
    client,_=setup
    for name in ('MAX_VIDEO_BYTES','LOCATION_RADIUS_METERS','MAX_GPS_ACCURACY_METERS'):monkeypatch.delenv(name,raising=False)
    config=client.get('/api/config').json()
    assert config['max_video_bytes']==20*1024*1024 and config['location_rules_configured']
    assert config['money_enabled'] is False
    monkeypatch.setenv('APP_ENV','production')
    config=client.get('/api/config').json()
    assert config['max_video_bytes'] is None and not config['location_rules_configured']


def test_nonseekable_webm_without_duration_is_processed(setup,monkeypatch):
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg required')
    client,factory=setup;headers=login(client)
    monkeypatch.delenv('AI_API_KEY',raising=False)
    data=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=30',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','1','-c:v','libvpx','-c:a','libopus','-f','webm','pipe:1'],capture_output=True,check=True).stdout
    item=client.post('/api/feedings',headers=headers,json=dict(request_key='webm-stream-test-12345',city='ignored',latitude=55,longitude=37,accuracy=10,mime_type='video/webm',size=len(data))).json()
    assert client.put('/api'+item['upload_path'],headers={**headers,'Content-Type':'video/webm'},content=data).status_code==204
    client.post(f"/api/feedings/{item['id']}/complete",headers=headers)
    result=process_video(item['id'],factory)
    assert result['status']=='READY',result


def test_ai_retry_reuses_mp4_and_cannot_double_award(setup,real_video,monkeypatch):
    from backend.processing import retry_ai
    client,factory=setup;headers=login(client)
    monkeypatch.delenv('AI_API_KEY',raising=False)
    fid=upload_video(client,headers,real_video)
    assert process_video(fid,factory)['feeding_status']=='REVIEW'
    monkeypatch.setattr('backend.processing.configured',lambda:True)
    monkeypatch.setattr('backend.processing.moderate',lambda frames:verdict())
    def unexpected(*args):raise AssertionError('Must reuse normalized media')
    monkeypatch.setattr('backend.processing.normalize',unexpected)
    assert retry_ai(fid,factory)['feeding_status']=='APPROVED'
    assert retry_ai(fid,factory)['status']=='unchanged'
    assert client.get('/api/me',headers=headers).json()['points']==10


@pytest.mark.parametrize('duration,audio',[(16,True),(1,False)])
def test_invalid_duration_or_missing_sound_never_awards(setup,tmp_path,duration,audio):
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg required')
    client,factory=setup;headers=login(client)
    source=tmp_path/'invalid.mp4'
    args=['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=5']
    if audio:args+=['-f','lavfi','-i','sine=frequency=440:sample_rate=44100']
    args+=['-t',str(duration),'-c:v','libx264','-preset','ultrafast']
    if audio:args+=['-c:a','aac']
    subprocess.run([*args,str(source)],check=True)
    fid=upload_video(client,headers,source.read_bytes())
    assert process_video(fid,factory)['status']=='INVALID'
    assert client.get('/api/me',headers=headers).json()['points']==0


def test_png_vision_request_preserves_correct_content_type(tmp_path,monkeypatch):
    monkeypatch.setenv('AI_API_KEY','unit-test-only');monkeypatch.setenv('AI_MODEL','provider-test')
    image=tmp_path/'test.png';image.write_bytes(b'png-fixture')
    def handle(request):
        payload=json.loads(request.content)
        image_data=payload['messages'][-1]['content'][-1]['image_url']['url']
        assert image_data.startswith('data:image/png;base64,')
        return httpx.Response(200,json={'choices':[{'message':{'content':verdict('REVIEW').model_dump_json()}}]})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert moderate([image],client).decision=='REVIEW'


def test_provider_http_failure_exposes_status_not_credentials(tmp_path,monkeypatch):
    monkeypatch.setenv('AI_API_KEY','unit-test-only');monkeypatch.setenv('AI_MODEL','provider-test')
    image=tmp_path/'test.jpg';image.write_bytes(b'jpeg-fixture')
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(401,json={'error':'private-provider-response'}))) as client:
        with pytest.raises(ProviderUnavailable) as failure:moderate([image],client)
    assert '401' in str(failure.value)
    assert 'private-provider-response' not in str(failure.value)
    assert 'unit-test-only' not in str(failure.value)


def test_local_ai_diagnostic_verifies_actual_image_content(monkeypatch,capsys):
    import importlib.util
    import base64
    import struct
    import zlib
    spec=importlib.util.spec_from_file_location('catfeedik_ai_diagnostic',Path(__file__).resolve().parents[2]/'scripts/check-ai.py')
    diagnostic=importlib.util.module_from_spec(spec);spec.loader.exec_module(diagnostic)
    monkeypatch.setenv('AI_API_KEY','unit-test-only');monkeypatch.setenv('AI_MODEL','provider-test')
    calls=[]
    def handle(request):
        calls.append(request)
        payload=json.loads(request.content)
        if len(calls)==1:
            encoded=payload['messages'][-1]['content'][-1]['image_url']['url'].split(',',1)[1]
            png=base64.b64decode(encoded);offset=8;compressed=b''
            while offset<len(png):
                size=struct.unpack('!I',png[offset:offset+4])[0]
                kind=png[offset+4:offset+8]
                if kind==b'IDAT':compressed+=png[offset+8:offset+8+size]
                offset+=size+12
            rows=zlib.decompress(compressed)
            palette={(255,0,0):'red',(0,255,0):'green',(0,0,255):'blue',(255,255,0):'yellow',(0,0,0):'black',(255,255,255):'white'}
            colors=[palette[tuple(rows[y*289+1+x*3:y*289+1+x*3+3])] for y in (16,48,80) for x in (16,48,80)]
            content=json.dumps({'cells':colors})
        else:content=verdict('REJECT').model_dump_json()
        return httpx.Response(200,json={'choices':[{'message':{'content':content}}]})
    actual_client=httpx.Client
    monkeypatch.setattr(diagnostic.httpx,'Client',lambda **kwargs:actual_client(transport=httpx.MockTransport(handle),**kwargs))
    assert diagnostic.main()==0
    output=capsys.readouterr().out
    assert 'PASS: vision and structured moderation work' in output and 'unit-test-only' not in output
    assert len(calls)==2


def test_provider_429_diagnostics_classify_and_hide_raw_values():
    from backend.ai import provider_error_details
    for message,category in [('Rate limit exceeded: private-test-key','request_rate_limit'),
                             ('insufficient_quota private-test-key','quota_or_balance'),
                             ('No available model capacity private-test-key','model_capacity'),
                             ('opaque private-test-key','not_specified')]:
        response=httpx.Response(429,text=message,headers={'Retry-After':'60'})
        result=provider_error_details(response)
        assert result=={'status':429,'category':category,'retry_after_seconds':60}
        assert 'private-test-key' not in json.dumps(result)
    response=httpx.Response(429,text='opaque',headers={'Retry-After':'private-test-key'})
    assert 'retry_after_seconds' not in provider_error_details(response)
