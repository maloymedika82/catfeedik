import hashlib
import math
import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal
import boto3
from botocore.config import Config
from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session as DBSession
from .auth import verify_init_data
from .db import Base, engine, get_db, User, Session, Feeding, Points, Audit, Leaderboard, SnapshotRun, uid

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)  # Initial development schema; versioned migrations required before production.
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

def storage():
    names = ('R2_ENDPOINT_URL','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET')
    if not all(os.getenv(name) for name in names):
        raise HTTPException(503, 'Хранилище видео ещё не подключено')
    endpoint = os.environ['R2_ENDPOINT_URL']
    if not endpoint.startswith('https://'):
        raise HTTPException(503, 'R2 требует HTTPS')
    return boto3.client('s3',endpoint_url=endpoint,aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],region_name='auto',config=Config(signature_version='s3v4'))

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
    return {'telegram_configured':bool(os.getenv('TELEGRAM_BOT_TOKEN')),'storage_configured':all(os.getenv(n) for n in ('R2_ENDPOINT_URL','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET')),'demo_login_enabled':os.getenv('APP_ENV')=='development' and os.getenv('ALLOW_DEV_LOGIN')=='1','location_rules_configured':all(os.getenv(n) for n in ('LOCATION_RADIUS_METERS','MAX_GPS_ACCURACY_METERS')),'max_video_bytes':int(os.environ['MAX_VIDEO_BYTES']) if os.getenv('MAX_VIDEO_BYTES') else None,'ai_configured':False}

class Login(BaseModel):
    init_data: str = Field(min_length=1,max_length=16000)

def login_result(db,user):
    token = secrets.token_urlsafe(32)
    db.add(Session(token_hash=hashlib.sha256(token.encode()).hexdigest(),user_id=user.id,expires_at=int(time.time())+86400))
    db.commit()
    return {'access_token':token,'user':profile(db,user)}

@app.post('/api/auth/telegram')
def telegram_login(data: Login,db: DB):
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
    return login_result(db,user)

@app.post('/api/auth/dev')
def dev_login(db: DB):
    if os.getenv('APP_ENV')!='development' or os.getenv('ALLOW_DEV_LOGIN')!='1':
        raise HTTPException(404,'Not found')
    user=db.scalar(select(User).where(User.telegram_id==-1))
    if not user:
        user=User(telegram_id=-1,name='Тестовый участник',city='Москва')
        db.add(user);db.flush()
    return login_result(db,user)

@app.post('/api/auth/logout',status_code=204)
def logout(db: DB,user: CurrentUser,authorization: Annotated[str,Header()]):
    item=db.get(Session,hashlib.sha256(authorization[7:].encode()).hexdigest())
    db.delete(item);db.commit()

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
    if not os.getenv('MAX_VIDEO_BYTES'):
        raise HTTPException(503,'Лимит видео ещё не утверждён')
    if data.size>int(os.environ['MAX_VIDEO_BYTES']):
        raise HTTPException(413,'Видео превышает допустимый размер')
    # Lock per participant to serialize retries and concurrent requests.
    locked_user=db.execute(select(User).where(User.id==user.id).with_for_update().execution_options(populate_existing=True)).scalar_one()
    active(locked_user)
    feeding=db.scalar(select(Feeding).where(Feeding.user_id==user.id,Feeding.request_key==data.request_key))
    if feeding and feeding.status!='UPLOADING':
        return {'id':feeding.id,'status':feeding.status,'upload_url':None}
    if feeding and any(getattr(feeding,k)!=v for k,v in data.model_dump().items() if k!='request_key'):
        raise HTTPException(409,'Повторная загрузка должна содержать тот же файл и метаданные')
    client=storage()
    if not feeding:
        feeding=Feeding(id=uid(),user_id=user.id,**data.model_dump(),object_key=f'originals/{user.id}/{uid()}')
        db.add(feeding);db.flush()
    url=client.generate_presigned_url('put_object',Params={'Bucket':os.environ['R2_BUCKET'],'Key':feeding.object_key,'ContentType':feeding.mime_type,'ContentLength':feeding.size,'IfNoneMatch':'*'},ExpiresIn=900)
    db.commit()
    return {'id':feeding.id,'status':feeding.status,'upload_url':url}

@app.post('/api/feedings/{feeding_id}/complete')
def complete(feeding_id:str,db: DB,user: CurrentUser):
    active(user)
    feeding=db.scalar(select(Feeding).where(Feeding.id==feeding_id,Feeding.user_id==user.id).with_for_update())
    if not feeding:
        raise HTTPException(404,'Видео не найдено')
    if feeding.status!='UPLOADING':
        return {'id':feeding.id,'status':feeding.status}
    try:
        head=storage().head_object(Bucket=os.environ['R2_BUCKET'],Key=feeding.object_key)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(409,'Не удалось подтвердить загрузку. Повторите запрос.') from None
    if head['ContentLength']!=feeding.size or head.get('ContentType')!=feeding.mime_type:
        raise HTTPException(422,'Метаданные загруженного файла не совпадают')
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
    # Raw media stays private. A short-lived link is issued only to administrators.
    client=storage()
    url=client.generate_presigned_url('get_object',Params={'Bucket':os.environ['R2_BUCKET'],'Key':feeding.object_key},ExpiresIn=300)
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
