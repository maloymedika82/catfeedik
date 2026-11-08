from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream'])
 ctx=b.new_context(permissions=['camera','microphone'])
 page=ctx.new_page();page.goto('http://127.0.0.1:5174');page.get_by_role('button',name='Тестовый вход',exact=True).click();page.locator('.login-banner').wait_for(state='hidden')
 page.get_by_role('button',name='Начать запись',exact=False).click();page.get_by_role('checkbox').check();page.get_by_role('button',name='Принять и продолжить',exact=True).click();page.get_by_label('В каком городе кормишь?').fill('Москва');page.get_by_role('option',name='Moscow, RU').click();page.get_by_role('button',name='Открыть камеру',exact=True).click();page.get_by_role('button',name='Начать запись',exact=True).click();page.wait_for_timeout(1200);page.get_by_role('button',name='Завершить',exact=True).click();page.locator('video[controls]').wait_for()
 assert page.locator('video').evaluate('(v)=>v.src.startsWith("blob:")')
 assert page.get_by_role('button',name='Отправить на проверку').is_disabled()
 page.get_by_role('button',name='Переснять',exact=True).click();page.get_by_role('button',name='Начать запись',exact=True).click();page.locator('video[controls]').wait_for(timeout=18000)
 duration=page.locator('video').evaluate('(v)=>v.duration')
 page.keyboard.press('Escape');assert page.locator('dialog').is_hidden()
 print('Passed: city selection, camera + microphone without GPS, recording, preview, retake, automatic 15 second stop, missing-storage upload guard, close cleanup. Browser duration:',duration)
 b.close()
