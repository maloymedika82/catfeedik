import os
import hashlib
import time
from typing import Annotated
from fastapi import Depends,HTTPException,Header
from sqlalchemy import select,func
from sqlalchemy.orm import Session as DBSession
from .db import get_db,User,Session,Points,Feeding

DB = Annotated[DBSession, Depends(get_db)]

def authenticated_user(db,token):
    if not token:raise HTTPException(401,'Войдите через Telegram')
    session=db.get(Session,hashlib.sha256(token.encode()).hexdigest())
    if not session or session.expires_at<=int(time.time()):raise HTTPException(401,'Сессия истекла')
    user=db.get(User,session.user_id)
    if not user or (user.telegram_id<0 and (os.getenv('APP_ENV')!='development' or os.getenv('ALLOW_DEV_LOGIN')!='1' or (user.role=='ADMIN' and os.getenv('ALLOW_DEV_ADMIN','1')!='1'))):
        raise HTTPException(401,'Тестовая сессия недоступна вне режима разработки')
    return user


def require_user(db:DB,authorization:Annotated[str | None,Header()]=None):
    if not authorization or not authorization.startswith('Bearer '):raise HTTPException(401,'Войдите через Telegram')
    return authenticated_user(db,authorization[7:])

CurrentUser = Annotated[User, Depends(require_user)]

def require_admin(user: CurrentUser):
    if user.role not in ('OWNER', 'ADMIN') or user.frozen:
        raise HTTPException(403, 'Нет доступа')
    return user
Admin = Annotated[User, Depends(require_admin)]

def active(user):
    if user.frozen:
        raise HTTPException(403, 'Аккаунт заморожен. Обратитесь в поддержку.')

def totals(db, user_id):
    points = db.scalar(select(func.coalesce(func.sum(Points.delta),0)).where(Points.user_id==user_id))
    count = db.scalar(select(func.count()).select_from(Feeding).where(Feeding.user_id==user_id,Feeding.status=='APPROVED'))
    return points, count

def profile(db,user):
    points,count = totals(db,user.id)
    return dict(id=user.id,name=user.name,city=user.city,language=user.language,points=points,feedings=count,frozen=user.frozen,role=user.role,wallet=user.wallet,photo_url=user.photo_url,notify_enabled=user.notify_enabled)

