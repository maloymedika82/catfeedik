"""Local end-to-end upload check. Uses temporary data, fake camera and test-only limits."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import uuid
import hashlib
import hmac
import json
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
python=root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
processes=[]

def wait_http(url):
    for _ in range(100):
        try:
            with urllib.request.urlopen(url,timeout=1) as response:
                if response.status==200:
                    return
        except OSError:
            time.sleep(.1)
    raise RuntimeError('Test server did not start')

with tempfile.TemporaryDirectory(prefix='catfeedik-upload-') as directory:
    target=Path(directory)
    env={**os.environ,'APP_ENV':'development','ALLOW_DEV_LOGIN':'1',
         'DATABASE_URL':'sqlite:///'+str(target/'test.db'),
         'VIDEO_STORAGE_DIR':str(target/'videos'),'VIDEO_MIN_FREE_BYTES':'0',
         'CATFEEDIK_VITE_CACHE_DIR':str(target/'vite-cache'),'MAX_VIDEO_BYTES':'10485760','AI_API_KEY':'','TELEGRAM_BOT_TOKEN':'local-e2e-test-only','OWNER_TELEGRAM_IDS':'2022054034',
         'REDIS_URL':'redis://127.0.0.1:6379/15','CELERY_QUEUE':'catfeedik-test-'+uuid.uuid4().hex,'CATFEEDIK_API_PROXY':'http://127.0.0.1:8003'}
    try:
        with (target/'servers.log').open('w') as log:
            processes.append(subprocess.Popen([str(python),'-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8003'],cwd=root,env=env,stdout=log,stderr=log))
            processes.append(subprocess.Popen(['node','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5177','--strictPort'],cwd=root,env=env,stdout=log,stderr=log))
            for args in (['worker','--pool=solo','--concurrency=1','--loglevel=WARNING'],['beat','--loglevel=WARNING','--schedule',str(target/'beat')]):
                processes.append(subprocess.Popen([str(python),'-m','celery','-A','backend.tasks.celery_app',*args],cwd=root,env=env,stdout=log,stderr=log))
            wait_http('http://127.0.0.1:8003/api/health')
            wait_http('http://127.0.0.1:5177')
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream'])
                context=browser.new_context(permissions=['camera','microphone','geolocation'],geolocation={'latitude':55.75,'longitude':37.61,'accuracy':10})
                page=context.new_page()
                errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('https://telegram.org/**',lambda route:route.abort())
                page.route('https://tile.openstreetmap.org/**',lambda route:route.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e1ebdd"/></svg>'))
                page.goto('http://127.0.0.1:5177')
                page.get_by_role('button',name='Тестовый вход',exact=True).click()
                page.locator('.login-banner').wait_for(state='hidden')
                page.get_by_role('button',name='НАЧАТЬ',exact=True).click();page.get_by_role('button',name='Принять и продолжить',exact=True).wait_for();page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(root/'artifacts'/'participation-terms-mobile.png'),full_page=True);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');assert page.get_by_role('button',name='Принять и продолжить',exact=True).is_disabled();page.get_by_role('checkbox').check();page.get_by_role('button',name='Принять и продолжить',exact=True).click()
                page.get_by_role('button',name='Открыть камеру',exact=True).click()
                page.get_by_role('button',name='Начать запись',exact=True).click()
                page.wait_for_timeout(1200)
                page.get_by_role('button',name='Завершить',exact=True).click()
                assert page.get_by_label('Ближайший город',exact=True).input_value()=='Moscow, RU'
                page.get_by_role('button',name='Отправить на проверку',exact=True).click()
                page.get_by_text('Видео отправлено',exact=True).wait_for()
                assert page.get_by_text('Статус: видео обрабатывается.',exact=False).is_visible()
                page.keyboard.press('Escape')
                page.get_by_role('button',name='Профиль',exact=True).click()
                page.get_by_role('button',name='Мои видео',exact=True).click()
                page.locator('.history-row').filter(has_text='Moscow, RU').wait_for()
                page.get_by_text('На ручной проверке',exact=True).wait_for(timeout=60000)
                items=page.evaluate("""async()=>{const response=await fetch('/api/me/feedings',{headers:{Authorization:'Bearer '+sessionStorage.getItem('catfeedik-session')}});return response.json()}""")
                assert len(items)==1
                media_url=f"http://127.0.0.1:5177/api/media/{items[0]['id']}"
                response=context.request.get(media_url,headers={'Range':'bytes=0-7'})
                assert response.status==206 and len(response.body())==8
                anonymous=browser.new_context()
                assert anonymous.request.get(media_url).status==401
                assert len(list((target/'videos'/'originals').glob('*/*')))==1
                assert len(list((target/'videos'/'processed').glob('*/*.mp4')))==1
                assert len(list((target/'videos'/'processed').glob('*/*.jpg')))==1
                # Authorize a test Owner with a test-only bot signature; never use real tokens.
                tg={'auth_date':str(int(time.time())),'user':json.dumps({'id':2022054034,'first_name':'Test Owner'})}
                secret=hmac.new(b'WebAppData',b'local-e2e-test-only',hashlib.sha256).digest()
                tg['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(tg.items())).encode(),hashlib.sha256).hexdigest()
                auth=context.request.post('http://127.0.0.1:5177/api/auth/telegram',data={'init_data':urlencode(tg)})
                assert auth.status==200
                admin={'Authorization':'Bearer '+auth.json()['access_token']}
                fid=items[0]['id']
                assert context.request.post(f'http://127.0.0.1:5177/api/admin/feedings/{fid}/claim',headers=admin).status==200
                decision=context.request.post(f'http://127.0.0.1:5177/api/admin/feedings/{fid}/decision',headers=admin,data={'decision':'APPROVED','reason':'Development-only media workflow test'})
                assert decision.status==200
                page.reload();page.get_by_text('Готовимся к старту',exact=True).wait_for()
                page.locator('.leaflet-control-zoom-in').click()
                page.locator('.city-accessible-list button').click()
                page.locator('.feed-video-card video').wait_for()
                page.get_by_role('button',name='Поставить лайк',exact=True).click()
                page.get_by_role('button',name='Убрать лайк',exact=True).wait_for()
                page.keyboard.press('Escape')
                public=anonymous.request.get(f'http://127.0.0.1:5177/api/public/videos/{fid}',headers={'Range':'bytes=0-15'})
                assert public.status==206 and len(public.body())==16
                # Exercise the separate admin UI with a development-only Admin session.
                user_token=page.evaluate("sessionStorage.getItem('catfeedik-session')")
                page.goto('http://127.0.0.1:5177/admin.html')
                page.get_by_role('button',name='Войти тестовым администратором',exact=True).click()
                page.get_by_role('heading',name='Панель управления',exact=True).wait_for()
                dev_admin_token=page.evaluate("sessionStorage.getItem('catfeedik-session')")
                page.get_by_role('button',name='Пользователи',exact=True).click()
                page.get_by_role('textbox',name='Поиск пользователей',exact=True).fill('Тестовый участник')
                page.get_by_role('button',name='Найти',exact=True).click()
                page.locator('.admin-user-row').filter(has_text='Тестовый участник').click()
                page.get_by_label('Причина операции',exact=True).fill('E2E points correction')
                page.get_by_label('Изменение поинтов (минус для списания)',exact=True).fill('5')
                # A successful mutation followed by a failed refresh must not invite a duplicate debit/credit.
                def failed_user_refresh(route):
                    route.fulfill(status=503,json={'detail':'Simulated failed refresh'})
                page.route('**/api/admin/users/*',failed_user_refresh)
                page.get_by_role('button',name='Применить корректировку',exact=True).click()
                page.get_by_text('Операция сохранена. Не удалось обновить данные:',exact=False).wait_for()
                assert page.get_by_role('button',name='Применить корректировку',exact=True).is_disabled()
                page.unroute('**/api/admin/users/*',failed_user_refresh)
                page.locator('.admin-user-row').filter(has_text='Тестовый участник').click()
                page.get_by_text('Баланс: 15 · кормлений: 1 · USER',exact=True).wait_for()
                page.get_by_label('Причина операции',exact=True).fill('E2E risk review')
                page.get_by_role('button',name='Заморозить пользователя',exact=True).click()
                page.get_by_role('button',name='Разморозить после проверки',exact=True).wait_for()
                page.get_by_label('Причина операции',exact=True).fill('E2E review complete')
                page.get_by_role('button',name='Разморозить после проверки',exact=True).click()
                page.get_by_role('button',name='Заморозить пользователя',exact=True).wait_for()
                page.get_by_role('button',name='Журнал',exact=True).click()
                page.get_by_text('POINTS_ADJUSTED',exact=True).wait_for()
                page.evaluate("token=>sessionStorage.setItem('catfeedik-session',token)",auth.json()['access_token'])
                page.reload();page.get_by_label('Причина изменения',exact=True).fill('E2E provider outage')
                page.get_by_role('button',name='Перейти на ручную проверку',exact=True).click()
                page.get_by_text('приостановлена',exact=True).wait_for()
                assert context.request.get('http://127.0.0.1:5177/api/config').json()['ai_moderation_enabled'] is False
                # Submit a second test-only video, reject it, then appeal to a different Admin.
                original=list((target/'videos'/'originals').glob('*/*'))[0].read_bytes()+b'e2e-second'
                user_headers={'Authorization':'Bearer '+user_token}
                second=context.request.post('http://127.0.0.1:5177/api/feedings',headers=user_headers,data={
                    'request_key':str(uuid.uuid4()),'city':'ignored','latitude':55.80,'longitude':37.61,
                    'accuracy':10,'mime_type':'video/mp4','size':len(original)})
                assert second.status==200
                second_id=second.json()['id']
                assert context.request.put('http://127.0.0.1:5177/api'+second.json()['upload_path'],headers={**user_headers,'Content-Type':'video/mp4'},data=original).status==204
                assert context.request.post(f'http://127.0.0.1:5177/api/feedings/{second_id}/complete',headers=user_headers).status==200
                for _ in range(120):
                    history=context.request.get('http://127.0.0.1:5177/api/me/feedings',headers=user_headers).json()
                    if next(f for f in history if f['id']==second_id)['status']=='REVIEW':break
                    time.sleep(.5)
                else:raise AssertionError('Second test video was not processed')
                assert context.request.post(f'http://127.0.0.1:5177/api/admin/feedings/{second_id}/claim',headers=admin).status==200
                assert context.request.post(f'http://127.0.0.1:5177/api/admin/feedings/{second_id}/decision',headers=admin,data={'decision':'REJECTED','reason':'E2E initial rejection'}).status==200
                page.evaluate("token=>sessionStorage.setItem('catfeedik-session',token)",user_token)
                page.goto('http://127.0.0.1:5177')
                page.get_by_role('button',name='Профиль',exact=True).click()
                page.get_by_role('button',name='Мои видео',exact=True).click()
                page.get_by_role('button',name='Подать апелляцию',exact=True).click()
                page.get_by_label('Причина апелляции',exact=True).fill('E2E please review the decision again')
                page.get_by_role('button',name='Отправить апелляцию',exact=True).click()
                page.get_by_text('Апелляция рассматривается',exact=True).wait_for()
                page.evaluate("token=>sessionStorage.setItem('catfeedik-session',token)",dev_admin_token)
                page.goto('http://127.0.0.1:5177/admin.html')
                page.get_by_role('button',name='Апелляции',exact=True).click()
                page.get_by_role('button',name='Рассмотреть',exact=True).click()
                page.get_by_label('Причина решения по апелляции',exact=True).fill('E2E second moderator verified video')
                page.get_by_role('button',name='Принять апелляцию',exact=True).click()
                page.get_by_text('Открытых апелляций нет.',exact=True).wait_for()
                assert context.request.get('http://127.0.0.1:5177/api/me',headers=user_headers).json()['points']==25
                # Owner creates a real task through the UI; a participant submits proof.
                page.evaluate("token=>sessionStorage.setItem('catfeedik-session',token)",auth.json()['access_token'])
                page.reload()
                page.get_by_role('button',name='Спонсоры',exact=True).click()
                page.get_by_role('button',name='Добавить спонсора',exact=True).click()
                page.get_by_label('Название спонсора',exact=True).fill('E2E test partner')
                page.get_by_label('Описание спонсора',exact=True).fill('Temporary partner for isolated browser verification')
                page.get_by_label('Опубликовать спонсора',exact=True).check()
                page.get_by_label('Причина изменения спонсора',exact=True).fill('E2E sponsor creation')
                page.get_by_role('button',name='Сохранить спонсора',exact=True).click()
                page.get_by_text('Спонсор сохранён.',exact=True).wait_for()
                page.get_by_role('button',name='Добавить задание',exact=True).click()
                page.get_by_label('Название задания',exact=True).fill('E2E community task')
                page.get_by_label('Условия выполнения',exact=True).fill('Describe an animal welfare activity for manual review')
                page.get_by_label('Награда за задание (поинты)',exact=True).fill('7')
                page.get_by_label('Срок отправки заявки (твоё местное время)',exact=True).fill(time.strftime('%Y-%m-%dT%H:%M',time.localtime(time.time()+86400)))
                page.get_by_label('Включить задание',exact=True).check()
                page.get_by_label('Причина изменения задания',exact=True).fill('E2E task creation')
                page.get_by_role('button',name='Сохранить задание',exact=True).click()
                page.get_by_text('Задание сохранено.',exact=True).wait_for()
                page.evaluate("token=>sessionStorage.setItem('catfeedik-session',token)",user_token)
                page.goto('http://127.0.0.1:5177')
                page.get_by_role('button',name='Спонсоры',exact=True).click()
                page.get_by_role('button',name='Выполнить задание',exact=True).click()
                page.get_by_label('Как выполнено задание',exact=True).fill('E2E participant describes completed welfare activity')
                page.get_by_role('button',name='Отправить заявку',exact=True).click()
                page.get_by_text('Заявка отправлена.',exact=False).wait_for()
                page.evaluate("token=>sessionStorage.setItem('catfeedik-session',token)",auth.json()['access_token'])
                page.goto('http://127.0.0.1:5177/admin.html')
                page.get_by_role('button',name='Заявки на задания',exact=True).click()
                page.get_by_role('button',name='Открыть заявку',exact=True).click()
                page.get_by_label('Причина решения по заданию',exact=True).fill('E2E manual task verification')
                page.get_by_role('button',name='Подтвердить задание',exact=True).click()
                page.get_by_text('Заявка подтверждена, поинты начислены.',exact=True).wait_for()
                participant=context.request.get('http://127.0.0.1:5177/api/me',headers=user_headers).json()
                assert participant['points']==32 and participant['feedings']==2,participant
                # Saved account consent skips the form on later recordings; denied GPS
                # is explained before requesting camera/microphone again.
                page.evaluate("token=>sessionStorage.setItem('catfeedik-session',token)",user_token)
                page.goto('http://127.0.0.1:5177')
                page.get_by_role('button',name='НАЧАТЬ',exact=True).click()
                page.get_by_role('button',name='Открыть камеру',exact=True).wait_for()
                assert page.get_by_role('button',name='Принять и продолжить',exact=True).count()==0
                page.evaluate("""()=>{window.testMediaCalls=0;navigator.mediaDevices.getUserMedia=async()=>{window.testMediaCalls++;throw Error('unexpected media request')};navigator.geolocation.getCurrentPosition=(_success,failure)=>failure({code:1})}""")
                page.get_by_role('button',name='Открыть камеру',exact=True).click()
                page.get_by_text('Доступ к геолокации запрещён.',exact=False).wait_for()
                assert page.evaluate('window.testMediaCalls')==0
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(root/'artifacts'/'location-permission-mobile.png'),full_page=True)
                page.evaluate("token=>sessionStorage.setItem('catfeedik-session',token)",auth.json()['access_token'])
                page.goto('http://127.0.0.1:5177/admin.html')
                page.get_by_role('button',name='Обзор',exact=True).click()
                page.get_by_role('heading',name='Режим модерации',exact=True).wait_for()
                page.set_viewport_size({'width':1440,'height':1100})
                page.screenshot(path=str(root/'artifacts'/'admin-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(root/'artifacts'/'admin-mobile.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                denied=context.request.get('http://127.0.0.1:5177/.local/services.env')
                assert denied.status==403
                assert not list((target/'videos'/'_incoming').iterdir())
                assert not errors,errors
                browser.close()
                print('Passed: explicit versioned participation consent, persisted acceptance and denied-GPS recovery without media requests; fake camera -> upload -> actual Celery/Redis/FFmpeg -> REVIEW -> Owner manual decision -> map marker -> public city feed -> like. Admin UI points/freeze/audit, Owner manual mode, user appeal and different-Admin resolution passed. Sponsor creation, task submission and manual once-only reward passed. Private/public range access and staging cleanup passed. Map interactions used local test tiles; real OSM network is not verified. Temporary data removed.')
    except Exception:
        print((target/'servers.log').read_text(errors='replace')[-4000:])
        if 'page' in locals() and not page.is_closed():
            print(page.locator('body').inner_text()[:2000])
        raise
    finally:
        for process in reversed(processes):
            process.terminate()
        for process in reversed(processes):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill();process.wait()
