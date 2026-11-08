"""Isolated HTTP deployment smoke; requires built catfeedik-{api,web}:local images and .env.production. Never targets application volumes."""
import os,subprocess,tempfile,urllib.request,json,uuid
from pathlib import Path
root=Path(__file__).resolve().parents[1]
env={k:v for k,v in os.environ.items() if k not in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH')}
env['APP_DOMAIN']='example.invalid'
with tempfile.TemporaryDirectory(prefix='catfeedik-deploy-') as temp:
    override=Path(temp)/'override.yaml'
    override.write_text('''x-test: &settings
  AI_API_KEY: ""
  AI_MODERATION_ENABLED: "0"
  TELEGRAM_BOT_TOKEN: "123:isolated_test_only"
  MAX_VIDEO_BYTES: "20971520"
services:
  api:
    environment: *settings
  worker:
    environment: *settings
  beat:
    environment: *settings
  web:
    image: catfeedik-web:local
    environment:
      APP_DOMAIN: ":80"
    ports: !override
      - "127.0.0.1:18081:80"
''')
    cmd=['docker','--host=unix:///var/run/docker.sock','compose','--env-file',str(root/'.env.production'),'-p','catfeedik-deploy-check-'+uuid.uuid4().hex[:8],'-f',str(root/'compose.production.yaml'),'-f',str(override)]
    try:
        subprocess.run(cmd+['up','-d','--no-build','--wait','--wait-timeout','90'],env=env,check=True,cwd=root)
        base='http://127.0.0.1:18081'
        local=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with local.open(base+'/api/health') as r:assert json.load(r)['database']=='postgresql'
        with local.open(base+'/api/config') as r:
            config=json.load(r);assert not config['demo_login_enabled'] and not config['demo_admin_enabled'] and not config['money_enabled']
        with local.open(base+'/admin.html') as r:assert b'<html' in r.read()
        try:local.open(base+'/api/auth/dev',data=b'{}')
        except urllib.error.HTTPError as e:assert e.code==404
        else:raise AssertionError('Development login was accessible')
        print('PASS: isolated production stack healthy, PostgreSQL, worker/beat running, built admin served, development auth disabled, money disabled. HTTP smoke only; public HTTPS/Telegram not tested.')
    except Exception:
        subprocess.run(cmd+['logs','--tail','35','api'],env=env,cwd=root)
        raise
    finally:
        subprocess.run(cmd+['down','-v'],env=env,cwd=root,check=True)
