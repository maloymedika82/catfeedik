from playwright.sync_api import sync_playwright
import json
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
 page=b.new_page(viewport={'width':1440,'height':1100})
 errors=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('http://127.0.0.1:5174');page.get_by_text('Готовимся к старту',exact=True).wait_for()
 assert page.get_by_text('Первый город появится здесь').is_visible()
 page.get_by_role('button',name='НАЧАТЬ',exact=True).click();assert page.get_by_text('Открой Catfeedik в Telegram',exact=True).is_visible();page.keyboard.press('Escape')
 page.get_by_role('button',name='Тестовый вход',exact=True).click();page.locator('.login-banner').wait_for(state='hidden')
 page.get_by_role('button',name='Спонсоры',exact=True).click();assert page.get_by_text('Готовим первые партнёрства').is_visible()
 page.get_by_role('button',name='Профиль',exact=True).click();page.get_by_label('Город',exact=True).fill('Казань');page.get_by_label('Адрес кошелька',exact=True).fill('test-public-address');page.get_by_role('button',name='Сохранить профиль').click();page.get_by_text('Профиль сохранён на сервере',exact=True).wait_for()
 page.reload();page.get_by_role('button',name='Профиль',exact=True).click();assert page.get_by_label('Город',exact=True).input_value()=='Казань'
 page.get_by_role('button',name='Мои видео',exact=True).click();assert page.get_by_text('Ты ещё не отправлял видео.').is_visible()
 page.get_by_role('button',name='Главная',exact=True).click();page.get_by_role('button',name='НАЧАТЬ',exact=True).click();page.get_by_role('button',name='Принять и продолжить',exact=True).wait_for();assert page.get_by_role('button',name='Принять и продолжить',exact=True).is_disabled();page.keyboard.press('Escape')
 page.get_by_text('Готовимся к старту',exact=True).wait_for();page.screenshot(path='/workspace/catfeedik/artifacts/react-desktop.png',full_page=True)
 open('/workspace/catfeedik/artifacts/react-dock-rendered.html','w').write(page.locator('.nav-demo').evaluate('(el)=>el.outerHTML'))
 page.set_viewport_size({'width':390,'height':844});page.get_by_text('Готовимся к старту',exact=True).wait_for();page.screenshot(path='/workspace/catfeedik/artifacts/react-mobile.png',full_page=True);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 page.emulate_media(reduced_motion='reduce');page.get_by_role('button',name='Профиль',exact=True).focus();page.keyboard.press('Enter');assert page.get_by_label('Город',exact=True).is_visible()
 page.get_by_role('button',name='Выйти',exact=True).click();page.get_by_text('Открой Mini App из Telegram',exact=False).wait_for()
 assert not errors,errors
 print(json.dumps({'passed':['anonymous access','login gate','development login','real profile API persistence across reload','sponsors empty state','feeding history','camera intro','logout','mobile overflow','keyboard/reduced motion'],'page_errors':errors}))
 b.close()
