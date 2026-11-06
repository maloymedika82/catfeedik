import asyncio
import errno
import tempfile
from pathlib import Path
import hashlib
import math
import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from fastapi import FastAPI, Depends, HTTPException, Header, Request, Response, Cookie
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session as DBSession
from .auth import verify_init_data
from .local_storage import storage_root, object_path, check_space, publish_file, cleanup_abandoned_uploads
from .db import Base, engine, get_db, User, Session, Feeding, Points, Audit, Leaderboard, SnapshotRun, uid

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)  # Initial development schema; versioned migrations required before production.
    cleanup_abandoned_uploads(storage_root())
    yield

app = FastAPI(title='Catfeedik API', version='0.1.0', lifespan=lifespan)
DB = Annotated[DBSession, Depends(get_db)]

def require_user(db: DB, authorization: Annotated[str | None, Header()] = None):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Войдите через Telegram')
    token_hash = hashlib.sha256(authorization[7:].encode()).hexdigest()
    session = db.get(Session, token_hash)
    if not session or session.expires_at <= int(time.time()):
        raise HTTPException(401, 'Сессия истекла')
    return db.get(User, session.user_id)

CurrentUser = Annotated[User, Depends(require_user)]

def require_admin(user: CurrentUser):
    if user.role not in ('OWNER', 'ADMIN'):
        raise HTTPException(403, 'Нет доступа')
    return user
Admin = Annotated[User, Depends(require_admin)]

def active(user):
    if user.frozen:
        raise HTTPException(403, 'Аккаунт заморожен. Обратитесь в поддержку.')

def video_limit():
    raw=os.getenv('MAX_VIDEO_BYTES')
    if not raw:
        return None
    try:
        amount=int(raw)
        if amount<=0:
            raise ValueError
        return amount
    except ValueError:
        raise HTTPException(503, 'Лимит видео должен быть положительным числом байт') from None


def media_cookie(response,token):
    response.set_cookie('catfeedik_media',token,max_age=86400,httponly=True,
                        secure=os.getenv('APP_ENV')!='development',samesite='strict',path='/api/media')


def totals(db, user_id):
    points = db.scalar(select(func.coalesce(func.sum(Points.delta),0)).where(Points.user_id==user_id))
    count = db.scalar(select(func.count()).select_from(Feeding).where(Feeding.user_id==user_id,Feeding.status=='APPROVED'))
    return points, count

def profile(db,user):
    points,count = totals(db,user.id)
    return dict(id=user.id,name=user.name,city=user.city,language=user.language,points=points,feedings=count,frozen=user.frozen,role=user.role,wallet=user.wallet)

@app.get('/api/health')
def health(db: DB):
    db.execute(select(1))
    return {'status':'ok','database':'sqlite-development' if engine.dialect.name=='sqlite' else 'postgresql'}

@app.get('/api/config')
def config():
    return {'telegram_configured':bool(os.getenv('TELEGRAM_BOT_TOKEN')),'storage_configured':bool(storage_root()),'storage_backend':'local','demo_login_enabled':os.getenv('APP_ENV')=='development' and os.getenv('ALLOW_DEV_LOGIN')=='1','location_rules_configured':all(os.getenv(n) for n in ('LOCATION_RADIUS_METERS','MAX_GPS_ACCURACY_METERS')),'max_video_bytes':video_limit(),'ai_configured':False}

class Login(BaseModel):
    init_data: str = Field(min_length=1,max_length=16000)

def login_result(db,user,response):
    token = secrets.token_urlsafe(32)
    db.add(Session(token_hash=hashlib.sha256(token.encode()).hexdigest(),user_id=user.id,expires_at=int(time.time())+86400))
    db.commit()
    media_cookie(response,token)
    return {'access_token':token,'user':profile(db,user)}

@app.post('/api/auth/telegram')
def telegram_login(data: Login,response: Response,db: DB):
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise HTTPException(503,'Telegram-бот ещё не подключён')
    try:
        tg=verify_init_data(data.init_data,token)
    except (ValueError,TypeError,KeyError):
        raise HTTPException(401,'Недействительные данные Telegram') from None
    user=db.scalar(select(User).where(User.telegram_id==tg['id']))
    if not user:
        user=User(telegram_id=tg['id'],name=tg.get('first_name','Участник')[:200],language='en' if tg.get('language_code','').startswith('en') else 'ru')
        db.add(user)
        db.flush()
    owner_ids={int(v) for v in os.getenv('OWNER_TELEGRAM_IDS','').split(',') if v.strip().isdigit()}
    user.role='OWNER' if tg['id'] in owner_ids else ('USER' if user.role=='OWNER' else user.role)
    return login_result(db,user,response)

@app.post('/api/auth/dev')
def dev_login(response: Response,db: DB):
    if os.getenv('APP_ENV')!='development' or os.getenv('ALLOW_DEV_LOGIN')!='1':
        raise HTTPException(404,'Not found')
    user=db.scalar(select(User).where(User.telegram_id==-1))
    if not user:
        user=User(telegram_id=-1,name='Тестовый участник',city='Москва')
        db.add(user);db.flush()
    return login_result(db,user,response)

@app.post('/api/auth/logout',status_code=204)
def logout(response: Response,db: DB,user: CurrentUser,authorization: Annotated[str,Header()]):
    item=db.get(Session,hashlib.sha256(authorization[7:].encode()).hexdigest())
    db.delete(item);db.commit()
    response.delete_cookie('catfeedik_media',path='/api/media')

@app.get('/api/me')
def me(db: DB,user: CurrentUser):
    return profile(db,user)

class ProfileEdit(BaseModel):
    city: str = Field(max_length=100)
    language: Literal['ru','en']
    wallet: str = Field(max_length=200)

@app.patch('/api/me')
def edit_me(data: ProfileEdit,db: DB,user: CurrentUser):
    active(user)
    for k,v in data.model_dump().items():
        setattr(user,k,v.strip())
    db.commit()
    return profile(db,user)

@app.get('/api/me/points')
def point_history(db: DB,user: CurrentUser):
    return [dict(id=p.id,delta=p.delta,reason=p.reason,created_at=p.created_at) for p in db.scalars(select(Points).where(Points.user_id==user.id).order_by(Points.created_at.desc()).limit(200))]

@app.get('/api/me/feedings')
def my_feedings(db: DB,user: CurrentUser):
    return [dict(id=f.id,city=f.city,status=f.status,created_at=f.created_at,reason=f.decision_reason) for f in db.scalars(select(Feeding).where(Feeding.user_id==user.id).order_by(Feeding.created_at.desc()).limit(200))]

@app.get('/api/stats')
def stats(db: DB):
    approved=Feeding.status=='APPROVED'
    return {'participants':db.scalar(select(func.count()).select_from(User)), 'feedings':db.scalar(select(func.count()).select_from(Feeding).where(approved)), 'cities':db.scalar(select(func.count(func.distinct(Feeding.city))).where(approved))}

@app.get('/api/cities')
def cities(db: DB):
    return [dict(name=name,feedings=count) for name,count in db.execute(select(Feeding.city,func.count()).where(Feeding.status=='APPROVED').group_by(Feeding.city))]

@app.get('/api/leaderboard')
def leaderboard(db: DB,offset:int=0,limit:int=50):
    if offset<0 or limit<1 or limit>100:
        raise HTTPException(422,'Invalid pagination')
    hour=int(time.time())//3600
    # Transaction-scoped lock serializes snapshot creation on PostgreSQL.
    if engine.dialect.name=='postgresql':
        from sqlalchemy import text
        db.execute(text('SELECT pg_advisory_xact_lock(714291)'))
    if not db.get(SnapshotRun,hour):
        candidates=[]
        for user in db.scalars(select(User).where(User.frozen==False)):
            points,count=totals(db,user.id)
            if not count and not points:
                continue
            achieved=db.scalar(select(func.max(Points.created_at)).where(Points.user_id==user.id)) or user.created_at
            candidates.append((user,points,count,achieved))
        candidates.sort(key=lambda x:(-x[1],-x[2],x[3],x[0].id))
        for rank,(user,points,count,_) in enumerate(candidates,1):
            db.add(Leaderboard(hour=hour,user_id=user.id,rank=rank,points=points,feedings=count))
        db.add(SnapshotRun(hour=hour))
        db.commit()
    records=db.execute(select(Leaderboard,User).join(User,User.id==Leaderboard.user_id).where(Leaderboard.hour==hour).order_by(Leaderboard.rank).offset(offset).limit(limit)).all()
    return {'updated_at':hour*3600,'next_update':(hour+1)*3600,'items':[dict(rank=row.rank,name=user.name,city=user.city,points=row.points,feedings=row.feedings) for row,user in records]}

class Upload(BaseModel):
    request_key: str = Field(min_length=16,max_length=80,pattern=r'^[a-zA-Z0-9-]+$')
    city: str = Field(min_length=1,max_length=100)
    latitude: float = Field(ge=-90,le=90)
    longitude: float = Field(ge=-180,le=180)
    accuracy: float = Field(gt=0,le=100000)
    mime_type: Literal['video/mp4','video/webm']
    size: int = Field(gt=0)

@app.post('/api/feedings')
def create_feeding(data: Upload,db: DB,user: CurrentUser):
    active(user)
    limit=video_limit()
    if not limit:
        raise HTTPException(503,'Лимит видео ещё не утверждён')
    if data.size>limit:
        raise HTTPException(413,'Видео превышает допустимый размер')
    # Lock per participant to serialize retries and concurrent requests.
    locked_user=db.execute(select(User).where(User.id==user.id).with_for_update().execution_options(populate_existing=True)).scalar_one()
    active(locked_user)
    feeding=db.scalar(select(Feeding).where(Feeding.user_id==user.id,Feeding.request_key==data.request_key))
    if feeding and feeding.status!='UPLOADING':
        return {'id':feeding.id,'status':feeding.status,'upload_path':None}
    if feeding and any(getattr(feeding,k)!=v for k,v in data.model_dump().items() if k!='request_key'):
        raise HTTPException(409,'Повторная загрузка должна содержать тот же файл и метаданные')
    root=storage_root()
    check_space(root,data.size)
    if not feeding:
        feeding=Feeding(id=uid(),user_id=user.id,**data.model_dump(),object_key=f'originals/{user.id}/{uid()}')
        db.add(feeding);db.flush()
    db.commit()
    return {'id':feeding.id,'status':feeding.status,'upload_path':f'/feedings/{feeding.id}/content'}


def prepare_upload(db,user_id,feeding_id):
    feeding=db.scalar(select(Feeding).where(Feeding.id==feeding_id,Feeding.user_id==user_id))
    if not feeding:
        raise HTTPException(404, 'Видео не найдено')
    if feeding.status!='UPLOADING':
        raise HTTPException(409, 'Видео уже передано на проверку')
    expected,mime=feeding.size,feeding.mime_type
    db.rollback()  # Do not keep a transaction/row lock open while waiting for the client.
    return expected,mime


def finish_upload(db,user_id,feeding_id,staged,digest):
    participant=db.scalar(select(User).where(User.id==user_id).with_for_update().execution_options(populate_existing=True))
    active(participant)
    feeding=db.scalar(select(Feeding).where(Feeding.id==feeding_id,Feeding.user_id==user_id).with_for_update().execution_options(populate_existing=True))
    if not feeding or feeding.status!='UPLOADING':
        raise HTTPException(409, 'Видео больше не принимает загрузку')
    publish_file(staged,feeding.object_key,digest)
    db.commit()


@app.put('/api/feedings/{feeding_id}/content',status_code=204)
async def upload_content(feeding_id:str,request: Request,db: DB,user: CurrentUser):
    active(user)
    user_id=user.id
    expected,mime=await run_in_threadpool(prepare_upload,db,user_id,feeding_id)
    limit=video_limit()
    if not limit:
        raise HTTPException(503, 'Лимит видео ещё не утверждён')
    if expected>limit:
        raise HTTPException(413, 'Видео превышает допустимый размер')
    if request.headers.get('content-type','').split(';',1)[0].strip().lower()!=mime:
        raise HTTPException(415, 'Тип файла не совпадает с сессией записи')
    length=request.headers.get('content-length')
    if length is not None:
        try:
            if int(length)!=expected:
                raise ValueError
        except ValueError:
            raise HTTPException(422, 'Размер файла не совпадает с сессией записи') from None
    root=storage_root()
    check_space(root,expected)
    staged=None
    try:
        with tempfile.NamedTemporaryFile(dir=root/'_incoming',suffix='.part',delete=False) as output:
            staged=Path(output.name)
            total=0
            digest=hashlib.sha256()
            async with asyncio.timeout(120):
                async for chunk in request.stream():
                    total+=len(chunk)
                    if total>expected or total>limit:
                        raise HTTPException(413, 'Загрузка превысила допустимый размер')
                    if chunk:
                        await run_in_threadpool(check_space,root,len(chunk))
                        await run_in_threadpool(output.write,chunk)
                        digest.update(chunk)
            if total!=expected:
                raise HTTPException(422, 'Видео загружено не полностью. Повторите отправку.')
            await run_in_threadpool(output.flush)
            await run_in_threadpool(os.fsync,output.fileno())
        await run_in_threadpool(finish_upload,db,user_id,feeding_id,staged,digest.hexdigest())
    except TimeoutError:
        raise HTTPException(408, 'Время загрузки истекло. Повторите отправку.') from None
    except OSError as exc:
        raise HTTPException(507 if exc.errno in (errno.ENOSPC,errno.EDQUOT) else 503,
                            'Не удалось сохранить видео на диске') from None
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


@app.post('/api/feedings/{feeding_id}/complete')
def complete(feeding_id:str,db: DB,user: CurrentUser):
    participant=db.scalar(select(User).where(User.id==user.id).with_for_update().execution_options(populate_existing=True))
    active(participant)
    feeding=db.scalar(select(Feeding).where(Feeding.id==feeding_id,Feeding.user_id==user.id).with_for_update().execution_options(populate_existing=True))
    if not feeding:
        raise HTTPException(404,'Видео не найдено')
    if feeding.status!='UPLOADING':
        return {'id':feeding.id,'status':feeding.status}
    path=object_path(feeding.object_key)
    if not path.is_file() or path.stat().st_size!=feeding.size:
        raise HTTPException(409,'Видео не загружено полностью. Повторите отправку.')
    feeding.status='REVIEW' # Human verification until FFmpeg and AI worker are connected.
    db.commit()
    return {'id':feeding.id,'status':feeding.status}

@app.get('/api/admin/queue')
def queue(db: DB,admin: Admin):
    return [dict(id=f.id,user_id=f.user_id,city=f.city,created_at=f.created_at,claimed_by=f.claimed_by,status=f.status) for f in db.scalars(select(Feeding).where(Feeding.status=='REVIEW').order_by(Feeding.created_at).limit(100))]

@app.post('/api/admin/feedings/{feeding_id}/claim')
def claim(feeding_id:str,db: DB,admin: Admin):
    result=db.execute(update(Feeding).where(Feeding.id==feeding_id,Feeding.status=='REVIEW',Feeding.claimed_by.is_(None)).values(claimed_by=admin.id))
    if not result.rowcount:
        raise HTTPException(409,'Видео уже занято или проверено')
    db.commit()
    return {'claimed_by':admin.id}

class Decision(BaseModel):
    decision: Literal['APPROVED','REJECTED']
    reason: str = Field(min_length=3,max_length=2000)


def distance(a,b):
    lat1,lon1,lat2,lon2=map(math.radians,(a.latitude,a.longitude,b.latitude,b.longitude))
    h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000*2*math.asin(min(1,math.sqrt(h)))

@app.post('/api/admin/feedings/{feeding_id}/decision')
def decide(feeding_id:str,data: Decision,db: DB,admin: Admin):
    # Lock user first consistently across decisions to serialize point thresholds.
    target=db.get(Feeding,feeding_id)
    if not target:
        raise HTTPException(404,'Видео не найдено')
    participant=db.scalar(select(User).where(User.id==target.user_id).with_for_update())
    feeding=db.scalar(select(Feeding).where(Feeding.id==feeding_id).with_for_update().execution_options(populate_existing=True))
    if feeding.status!='REVIEW' or feeding.claimed_by!=admin.id:
        raise HTTPException(409,'Возьмите доступное видео в работу')
    if participant.frozen:
        raise HTTPException(409,'Аккаунт заморожен')
    if data.decision=='APPROVED':
        if not os.getenv('LOCATION_RADIUS_METERS') or not os.getenv('MAX_GPS_ACCURACY_METERS'):
            raise HTTPException(503,'Радиус локации и точность GPS ещё не утверждены')
        radius=float(os.environ['LOCATION_RADIUS_METERS']);accuracy=float(os.environ['MAX_GPS_ACCURACY_METERS'])
        if radius<=0 or accuracy<=0 or feeding.accuracy>accuracy:
            raise HTTPException(422,'Точность геолокации недостаточна')
        previous=db.scalars(select(Feeding).where(Feeding.user_id==participant.id,Feeding.status=='APPROVED')).all()
        if any(abs(feeding.created_at-old.created_at)<7*86400 and distance(feeding,old)<=radius for old in previous):
            raise HTTPException(409,'Повторный зачёт в этой локации доступен через 7 дней')
        db.add(Points(user_id=participant.id,event_key=f'feeding:{feeding.id}',delta=10,reason='Подтверждённое кормление'))
        if len(previous)==4:
            db.add(Points(user_id=participant.id,event_key=f'five:{participant.id}',delta=5,reason='Бонус за пять кормлений'))
    feeding.status=data.decision;feeding.decision_reason=data.reason
    db.add(Audit(actor_id=admin.id,action=data.decision,target=feeding.id,reason=data.reason))
    db.commit()
    return {'id':feeding.id,'status':feeding.status}

@app.get('/api/admin/feedings/{feeding_id}')
def admin_feeding(feeding_id:str,db: DB,admin: Admin):
    feeding=db.get(Feeding,feeding_id)
    if not feeding:
        raise HTTPException(404,'Видео не найдено')
    url=f'/api/media/{feeding.id}'
    participant=db.get(User,feeding.user_id)
    return {'id':feeding.id,'status':feeding.status,'city':feeding.city,'name':participant.name,'claimed_by':feeding.claimed_by,'video_url':url,'created_at':feeding.created_at,'reason':feeding.decision_reason,'ai_status':'NOT_CONNECTED'}

class Freeze(BaseModel):
    frozen: bool
    reason: str = Field(min_length=3,max_length=2000)

@app.post('/api/admin/users/{user_id}/freeze')
def freeze(user_id:str,data: Freeze,db: DB,admin: Admin):
    participant=db.scalar(select(User).where(User.id==user_id).with_for_update())
    if not participant:
        raise HTTPException(404,'Пользователь не найден')
    if participant.role in ('ADMIN','OWNER'):
        raise HTTPException(403,'Изменение административных аккаунтов здесь недоступно')
    participant.frozen=data.frozen
    if data.frozen:
        db.execute(update(Feeding).where(Feeding.user_id==participant.id,Feeding.status.in_(['UPLOADING','REVIEW'])).values(status='REJECTED',decision_reason='Аккаунт заморожен: '+data.reason))
    db.add(Audit(actor_id=admin.id,action='FREEZE' if data.frozen else 'UNFREEZE',target=participant.id,reason=data.reason))
    db.commit()
    return {'id':participant.id,'frozen':participant.frozen}

@app.post('/api/admin/feedings/{feeding_id}/release')
def release(feeding_id:str,db: DB,admin: Admin):
    if admin.role!='OWNER':
        raise HTTPException(403,'Только Owner может вернуть видео в очередь')
    result=db.execute(update(Feeding).where(Feeding.id==feeding_id,Feeding.status=='REVIEW').values(claimed_by=None))
    if not result.rowcount:
        raise HTTPException(404,'Видео не найдено в очереди')
    db.add(Audit(actor_id=admin.id,action='RELEASE',target=feeding_id,reason='Возврат в общую очередь'))
    db.commit()
    return {'status':'REVIEW'}


@app.get('/api/media/{feeding_id}')
def private_media(feeding_id:str,db: DB,
                  authorization: Annotated[str | None,Header()]=None,
                  media_session: Annotated[str | None,Cookie(alias='catfeedik_media')]=None):
    # Video elements cannot set bearer headers. Their same-origin HttpOnly cookie
    # is scoped to this read-only route; write endpoints still require bearer auth.
    token=authorization[7:] if authorization and authorization.startswith('Bearer ') else media_session
    if not token:
        raise HTTPException(401,'Войдите через Telegram')
    session=db.get(Session,hashlib.sha256(token.encode()).hexdigest())
    if not session or session.expires_at<=int(time.time()):
        raise HTTPException(401,'Сессия истекла')
    user=db.get(User,session.user_id)
    feeding=db.get(Feeding,feeding_id)
    if not feeding or (feeding.user_id!=user.id and user.role not in ('ADMIN','OWNER')):
        raise HTTPException(404,'Видео не найдено')
    if feeding.status=='UPLOADING':
        raise HTTPException(409,'Видео ещё не отправлено на проверку')
    path=object_path(feeding.object_key)
    if not path.is_file():
        raise HTTPException(404,'Файл видео не найден на сервере')
    return FileResponse(path,media_type=feeding.mime_type,
                        headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
