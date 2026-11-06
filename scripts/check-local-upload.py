"""Local end-to-end upload check. Uses temporary data, fake camera and test-only limits."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
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
         'MAX_VIDEO_BYTES':'10485760','CATFEEDIK_API_PROXY':'http://127.0.0.1:8003'}
    try:
        with (target/'servers.log').open('w') as log:
            processes.append(subprocess.Popen([str(python),'-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8003'],cwd=root,env=env,stdout=log,stderr=log))
            processes.append(subprocess.Popen(['node','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5177','--strictPort'],cwd=root,env=env,stdout=log,stderr=log))
            wait_http('http://127.0.0.1:8003/api/health')
            wait_http('http://127.0.0.1:5177')
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream'])
                context=browser.new_context(permissions=['camera','microphone','geolocation'],geolocation={'latitude':55.75,'longitude':37.61,'accuracy':10})
                page=context.new_page()
                errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('https://telegram.org/**',lambda route:route.abort())
                page.goto('http://127.0.0.1:5177')
                page.get_by_role('button',name='Тестовый вход',exact=True).click()
                page.locator('.login-banner').wait_for(state='hidden')
                page.get_by_role('button',name='НАЧАТЬ',exact=True).click()
                page.get_by_role('button',name='Разрешить доступ и открыть камеру').click()
                page.get_by_role('button',name='Начать запись',exact=True).click()
                page.wait_for_timeout(1200)
                page.get_by_role('button',name='Завершить',exact=True).click()
                page.get_by_label('Город',exact=True).fill('Тестовый город')
                page.get_by_role('button',name='Отправить на проверку',exact=True).click()
                page.get_by_text('Видео отправлено',exact=True).wait_for()
                assert page.get_by_text('Статус: ожидает ручной проверки.',exact=False).is_visible()
                page.keyboard.press('Escape')
                page.get_by_role('button',name='Профиль',exact=True).click()
                page.get_by_role('button',name='Мои видео',exact=True).click()
                page.locator('.history-row').filter(has_text='Тестовый город').wait_for()
                assert page.get_by_text('На ручной проверке',exact=True).is_visible()
                items=page.evaluate("""async()=>{const response=await fetch('/api/me/feedings',{headers:{Authorization:'Bearer '+sessionStorage.getItem('catfeedik-session')}});return response.json()}""")
                assert len(items)==1
                media_url=f"http://127.0.0.1:5177/api/media/{items[0]['id']}"
                response=context.request.get(media_url,headers={'Range':'bytes=0-7'})
                assert response.status==206 and len(response.body())==8
                anonymous=browser.new_context()
                assert anonymous.request.get(media_url).status==401
                files=list((target/'videos'/'originals').glob('*/*'))
                assert len(files)==1 and files[0].stat().st_size>1000
                denied=context.request.get('http://127.0.0.1:5177/.local/services.env')
                assert denied.status==403
                assert not list((target/'videos'/'_incoming').iterdir())
                assert not errors,errors
                browser.close()
                print('Passed: fake-camera recording -> authenticated local upload -> REVIEW -> profile history; private ranged playback; anonymous denial; Vite private-file denial; staging cleanup. Temporary test data removed.')
    finally:
        for process in reversed(processes):
            process.terminate()
        for process in reversed(processes):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill();process.wait()
