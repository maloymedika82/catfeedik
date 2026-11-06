import hashlib
import json
import time
from typing import Literal
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select,func,or_,update,text
from .db import User,Feeding,Points,Audit,VideoAsset,AICheck,Appeal,PointAdjustment,RuntimeControl,AIRetry
from .schemas import Reasoned
from .dependencies import DB,Admin,CurrentUser,active,totals
from .awards import award
from .ai_control import enabled,next_provider_time
from .ai import configured

router=APIRouter()

def owner(admin):
    if admin.role!='OWNER':raise HTTPException(403,'Требуется роль Owner')


def person(db,user):
    points,count=totals(db,user.id)
    return dict(id=user.id,name=user.name,telegram_id=user.telegram_id,city=user.city,points=points,
                feedings=count,frozen=user.frozen,role=user.role,created_at=user.created_at)

@router.get('/api/admin/dashboard')
def dashboard(db:DB,admin:Admin):
    counts=dict(db.execute(select(Feeding.status,func.count()).group_by(Feeding.status)).all())
    return {'participants':db.scalar(select(func.count()).select_from(User)),
            'frozen':db.scalar(select(func.count()).select_from(User).where(User.frozen==True)),
            'feedings':sum(counts.values()),'statuses':counts,
            'points':db.scalar(select(func.coalesce(func.sum(Points.delta),0))),
            'appeals':db.scalar(select(func.count()).select_from(Appeal).where(Appeal.status=='OPEN')),
            'money_enabled':False,'ai_enabled':enabled(db),'ai_configured':configured(),
            'ai_wait_seconds':max(0,next_provider_time(db)-int(time.time()))}

@router.get('/api/admin/users')
def users(db:DB,admin:Admin,q:str='',offset:int=0,limit:int=30):
    if offset<0 or not 1<=limit<=100 or len(q)>100:raise HTTPException(422,'Недопустимые параметры поиска')
    query=select(User)
    if q.strip():
        pattern='%'+q.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        terms=[User.name.ilike(pattern,escape='\\'),User.city.ilike(pattern,escape='\\')]
        if q.strip().lstrip('-').isdigit() and -(2**63)<=int(q.strip())<2**63:terms.append(User.telegram_id==int(q.strip()))
        query=query.where(or_(*terms))
    rows=db.scalars(query.order_by(User.created_at.desc(),User.id).offset(offset).limit(limit+1)).all()
    return {'items':[person(db,u) for u in rows[:limit]],'has_more':len(rows)>limit}

@router.get('/api/admin/users/{user_id}')
def user_detail(user_id:str,db:DB,admin:Admin):
    user=db.get(User,user_id)
    if not user:raise HTTPException(404,'Пользователь не найден')
    return {'user':person(db,user),
            'feedings':[dict(id=f.id,status=f.status,city=f.city,reason=f.decision_reason,created_at=f.created_at) for f in db.scalars(select(Feeding).where(Feeding.user_id==user_id).order_by(Feeding.created_at.desc()).limit(100))],
            'points':[dict(id=p.id,delta=p.delta,reason=p.reason,created_at=p.created_at) for p in db.scalars(select(Points).where(Points.user_id==user_id).order_by(Points.created_at.desc()).limit(100))]}

class Adjust(Reasoned):
    request_key:str=Field(min_length=16,max_length=80,pattern=r'^[A-Za-z0-9-]+$')
    delta:int=Field(ge=-1000000,le=1000000)
    reason:str=Field(min_length=3,max_length=1000)

@router.post('/api/admin/users/{user_id}/points')
def adjust_points(user_id:str,data:Adjust,db:DB,admin:Admin):
    if data.delta==0:raise HTTPException(422,'Операция не может быть нулевой')
    if db.bind.dialect.name=='postgresql':
        lock=int(hashlib.sha256((admin.id+':'+data.request_key).encode()).hexdigest()[:15],16)
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':lock})
    existing=db.scalar(select(PointAdjustment).where(PointAdjustment.actor_id==admin.id,PointAdjustment.request_key==data.request_key))
    if existing:
        if (existing.user_id,existing.delta,existing.reason)!=(user_id,data.delta,data.reason):
            raise HTTPException(409,'Повтор операции должен содержать те же данные')
        return dict(id=existing.id,old_balance=existing.old_balance,new_balance=existing.new_balance)
    user=db.scalar(select(User).where(User.id==user_id).with_for_update().execution_options(populate_existing=True))
    if not user:raise HTTPException(404,'Пользователь не найден')
    active(user)
    old,_=totals(db,user_id);new=old+data.delta
    if new<0:raise HTTPException(409,'Списание превышает текущий баланс')
    receipt=PointAdjustment(actor_id=admin.id,user_id=user_id,request_key=data.request_key,delta=data.delta,
                            old_balance=old,new_balance=new,reason=data.reason)
    db.add(receipt);db.flush()
    db.add(Points(user_id=user_id,event_key='manual:'+receipt.id,delta=data.delta,reason='Корректировка: '+data.reason))
    db.add(Audit(actor_id=admin.id,action='POINTS_ADJUSTED',target=user_id,
                 reason=json.dumps({'reason':data.reason,'old_balance':old,'new_balance':new,'delta':data.delta},ensure_ascii=False)))
    db.commit()
    return dict(id=receipt.id,old_balance=old,new_balance=new)

class RoleChange(Reasoned):
    role:Literal['USER','ADMIN']
    reason:str=Field(min_length=3,max_length=1000)

@router.patch('/api/admin/users/{user_id}/role')
def change_role(user_id:str,data:RoleChange,db:DB,admin:Admin):
    owner(admin)
    user=db.scalar(select(User).where(User.id==user_id).with_for_update())
    if not user:raise HTTPException(404,'Пользователь не найден')
    if user.role=='OWNER':raise HTTPException(403,'Owner задаётся только конфигурацией сервера')
    if data.role=='ADMIN' and user.frozen:raise HTTPException(409,'Сначала разморозьте пользователя после проверки')
    old=user.role;user.role=data.role
    db.add(Audit(actor_id=admin.id,action='ROLE_CHANGED',target=user.id,reason=json.dumps({'from':old,'to':data.role,'reason':data.reason},ensure_ascii=False)))
    db.commit();return {'id':user.id,'role':user.role}

class AIControl(Reasoned):
    enabled:bool
    reason:str=Field(min_length=3,max_length=1000)

@router.patch('/api/admin/ai')
def control_ai(data:AIControl,db:DB,admin:Admin):
    owner(admin)
    item=db.get(RuntimeControl,'ai_enabled')
    if not item:item=RuntimeControl(name='ai_enabled',value='0');db.add(item)
    item.value='1' if data.enabled else '0'
    db.add(Audit(actor_id=admin.id,action='AI_ENABLED' if data.enabled else 'AI_PAUSED',target='ai',reason=data.reason))
    db.commit();return {'enabled':data.enabled}

@router.get('/api/admin/audit')
def audit(db:DB,admin:Admin,offset:int=0,limit:int=50):
    if offset<0 or not 1<=limit<=100:raise HTTPException(422,'Недопустимая страница')
    rows=db.execute(select(Audit,User.name).join(User,User.id==Audit.actor_id).order_by(Audit.created_at.desc(),Audit.id).offset(offset).limit(limit+1)).all()
    return {'items':[dict(id=a.id,actor=name,action=a.action,target=a.target,reason=a.reason,created_at=a.created_at) for a,name in rows[:limit]],'has_more':len(rows)>limit}

class AppealRequest(Reasoned):
    reason:str=Field(min_length=10,max_length=2000)

@router.post('/api/feedings/{feeding_id}/appeal')
def open_appeal(feeding_id:str,data:AppealRequest,db:DB,user:CurrentUser):
    feeding=db.scalar(select(Feeding).where(Feeding.id==feeding_id,Feeding.user_id==user.id).with_for_update())
    if not feeding:raise HTTPException(404,'Видео не найдено')
    existing=db.scalar(select(Appeal).where(Appeal.feeding_id==feeding_id))
    if existing:
        if existing.reason!=data.reason:raise HTTPException(409,'Апелляция уже отправлена и не редактируется')
        return {'id':existing.id,'status':existing.status}
    if feeding.status!='REJECTED':raise HTTPException(409,'Апелляция доступна только для отклонённого видео')
    original=db.scalar(select(Audit.actor_id).where(Audit.target==feeding_id,Audit.action=='REJECTED').order_by(Audit.created_at.desc()).limit(1))
    appeal=Appeal(feeding_id=feeding_id,user_id=user.id,original_reviewer=original,reason=data.reason)
    db.add(appeal);db.commit();return {'id':appeal.id,'status':appeal.status}

@router.get('/api/me/appeals')
def own_appeals(db:DB,user:CurrentUser):
    return [dict(id=a.id,feeding_id=a.feeding_id,status=a.status,reason=a.reason,decision_reason=a.decision_reason,created_at=a.created_at)
            for a in db.scalars(select(Appeal).where(Appeal.user_id==user.id).order_by(Appeal.created_at.desc()).limit(100))]

@router.get('/api/admin/appeals')
def appeals(db:DB,admin:Admin):
    rows=db.execute(select(Appeal,User.name,Feeding.city).join(User,User.id==Appeal.user_id).join(Feeding,Feeding.id==Appeal.feeding_id)
         .where(Appeal.status=='OPEN').order_by(Appeal.created_at).limit(100)).all()
    return [dict(id=a.id,feeding_id=a.feeding_id,name=name,city=city,reason=a.reason,claimed_by=a.claimed_by,
                 can_review=a.original_reviewer!=admin.id,original_reviewer=a.original_reviewer) for a,name,city in rows]

@router.post('/api/admin/appeals/{appeal_id}/claim')
def claim_appeal(appeal_id:str,db:DB,admin:Admin):
    appeal=db.scalar(select(Appeal).where(Appeal.id==appeal_id).with_for_update())
    if not appeal or appeal.status!='OPEN':raise HTTPException(404,'Апелляция не найдена')
    if appeal.original_reviewer==admin.id:raise HTTPException(403,'Первоначальный модератор не может рассматривать эту апелляцию')
    if appeal.claimed_by and appeal.claimed_by!=admin.id:raise HTTPException(409,'Апелляция уже занята')
    appeal.claimed_by=admin.id;db.commit();return {'id':appeal.id,'claimed_by':admin.id}

class AppealDecision(Reasoned):
    decision:Literal['ACCEPTED','REJECTED']
    reason:str=Field(min_length=3,max_length=2000)

@router.post('/api/admin/appeals/{appeal_id}/decision')
def decide_appeal(appeal_id:str,data:AppealDecision,db:DB,admin:Admin):
    target=db.get(Appeal,appeal_id)
    if not target:raise HTTPException(404,'Апелляция не найдена')
    user=db.scalar(select(User).where(User.id==target.user_id).with_for_update())
    feeding=db.scalar(select(Feeding).where(Feeding.id==target.feeding_id).with_for_update())
    appeal=db.scalar(select(Appeal).where(Appeal.id==appeal_id).with_for_update().execution_options(populate_existing=True))
    if appeal.original_reviewer==admin.id:raise HTTPException(403,'Нужен другой модератор')
    if appeal.status!='OPEN' or appeal.claimed_by!=admin.id:raise HTTPException(409,'Возьмите открытую апелляцию в работу')
    if feeding.status!='REJECTED':raise HTTPException(409,'Решение по видео уже изменилось')
    if data.decision=='ACCEPTED':
        active(user);award(db,user,feeding)
        feeding.status='APPROVED';feeding.decision_reason='Апелляция принята: '+data.reason
    appeal.status=data.decision;appeal.decision_reason=data.reason;appeal.resolved_at=int(time.time())
    db.add(Audit(actor_id=admin.id,action='APPEAL_'+data.decision,target=feeding.id,reason=data.reason))
    db.commit();return {'id':appeal.id,'status':appeal.status,'feeding_status':feeding.status}

class RetryAppeal(Reasoned):
    reason:str=Field(min_length=3,max_length=1000)

@router.post('/api/admin/appeals/{appeal_id}/retry-processing')
def retry_appeal_media(appeal_id:str,data:RetryAppeal,db:DB,admin:Admin):
    appeal=db.scalar(select(Appeal).where(Appeal.id==appeal_id).with_for_update())
    if not appeal or appeal.status!='OPEN':raise HTTPException(404,'Открытая апелляция не найдена')
    if appeal.original_reviewer==admin.id:raise HTTPException(403,'Нужен другой модератор')
    if appeal.claimed_by!=admin.id:raise HTTPException(409,'Возьмите апелляцию в работу')
    feeding=db.get(Feeding,appeal.feeding_id)
    if feeding.status!='REJECTED':raise HTTPException(409,'Решение по видео уже изменилось')
    asset=db.scalar(select(VideoAsset).where(VideoAsset.feeding_id==feeding.id).with_for_update())
    if asset and asset.status not in ('ERROR','INVALID'):raise HTTPException(409,'Повторная техническая обработка недоступна')
    if not asset:asset=VideoAsset(feeding_id=feeding.id);db.add(asset)
    asset.status='PENDING';asset.attempts=0
    db.add(Audit(actor_id=admin.id,action='APPEAL_RETRY_PROCESSING',target=feeding.id,reason=data.reason))
    db.commit();return {'status':'PENDING'}
