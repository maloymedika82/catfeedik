"""Owner-managed sponsor tasks with explicitly manual confirmation and exactly-once points."""
import hashlib
import json
import time
from typing import Annotated,Literal
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field,HttpUrl,field_validator,ConfigDict,AfterValidator
from sqlalchemy import select,func,text
from .db import Sponsor,SponsorTask,TaskApplication,User,Points,Audit
from .dependencies import DB,Admin,CurrentUser,active
from .administration import owner
from .schemas import Reasoned

router=APIRouter()


def clean(value):
    if '\x00' in value:raise ValueError('Недопустимый символ в тексте')
    return value.strip()

Name=Annotated[str,AfterValidator(clean),Field(min_length=2,max_length=120)]
Description=Annotated[str,AfterValidator(clean),Field(min_length=10,max_length=4000)]
RequestKey=Annotated[str,Field(min_length=16,max_length=80,pattern=r'^[A-Za-z0-9-]+$')]

class StrictReason(Reasoned):
    model_config=ConfigDict(extra='forbid')
    reason:str=Field(min_length=3,max_length=1000)

class SponsorData(StrictReason):
    name:Name
    description:Description
    logo_url:str=Field(default='',max_length=2048)
    active:bool=False

    @field_validator('logo_url')
    @classmethod
    def logo_https(cls,value):
        return validate_url(value)

class SponsorCreate(SponsorData):
    request_key:RequestKey

class TaskData(StrictReason):
    title:Annotated[str,AfterValidator(clean),Field(min_length=3,max_length=150)]
    conditions:Description
    reward_points:int=Field(ge=1,le=1000000,strict=True)
    deadline_at:int=Field(gt=0,lt=2**63,strict=True)
    active:bool=False

class TaskCreate(TaskData):
    request_key:RequestKey

class ApplicationData(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_key:RequestKey
    terms_hash:str=Field(pattern=r'^[a-f0-9]{64}$')
    evidence:Description
    evidence_url:str=Field(default='',max_length=2048)

    @field_validator('evidence_url')
    @classmethod
    def evidence_https(cls,value):
        return validate_url(value)

class ApplicationDecision(StrictReason):
    decision:Literal['APPROVED','REJECTED']


def validate_url(value):
    value=value.strip()
    if not value:return ''
    url=HttpUrl(value)
    if url.scheme!='https':raise ValueError('Требуется HTTPS-ссылка')
    if url.username or url.password:raise ValueError('URL не должен содержать логин или пароль')
    return str(url)


def operation_lock(db,namespace,actor,key):
    if db.bind.dialect.name=='postgresql':
        digest=hashlib.sha256((namespace+':'+actor+':'+key).encode()).hexdigest()
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':int(digest[:15],16)})


def fingerprint(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def page(offset,limit):
    if offset<0 or not 1<=limit<=100:raise HTTPException(422,'Недопустимая страница')


def task_terms(task):
    return fingerprint({'title':task.title,'conditions':task.conditions,'reward_points':task.reward_points,'deadline_at':task.deadline_at})


def task_dict(task):
    return dict(id=task.id,sponsor_id=task.sponsor_id,title=task.title,conditions=task.conditions,
                reward_points=task.reward_points,deadline_at=task.deadline_at,active=task.active,
                verification='MANUAL_OWNER',created_at=task.created_at,terms_hash=task_terms(task))


def sponsor_dict(sponsor):
    return dict(id=sponsor.id,name=sponsor.name,description=sponsor.description,logo_url=sponsor.logo_url,
                active=sponsor.active,created_at=sponsor.created_at)


def application_dict(item):
    return dict(id=item.id,task_id=item.task_id,status=item.status,attempt=item.attempt,
                task_title=item.task_title,sponsor_name=item.sponsor_name,conditions=item.conditions_snapshot,
                reward_points=item.reward_points,deadline_at=item.deadline_at,terms_hash=item.terms_hash,evidence=item.evidence,
                evidence_url=item.evidence_url,review_reason=item.review_reason,created_at=item.created_at,
                reviewed_at=item.reviewed_at)

@router.get('/api/sponsors')
def public_sponsors(db:DB,offset:int=0,limit:int=20):
    page(offset,limit)
    sponsors=db.scalars(select(Sponsor).where(Sponsor.active==True).order_by(Sponsor.created_at,Sponsor.id).offset(offset).limit(limit+1)).all()
    result=[]
    for sponsor in sponsors[:limit]:
        tasks=db.scalars(select(SponsorTask).where(SponsorTask.sponsor_id==sponsor.id,SponsorTask.active==True,
                          SponsorTask.deadline_at>int(time.time())).order_by(SponsorTask.deadline_at,SponsorTask.id).limit(11)).all()
        result.append({**sponsor_dict(sponsor),'tasks':[task_dict(t) for t in tasks[:10]],'tasks_has_more':len(tasks)>10})
    return {'items':result,'has_more':len(sponsors)>limit}

@router.get('/api/admin/sponsors')
def managed_sponsors(db:DB,admin:Admin,offset:int=0,limit:int=30):
    owner(admin);page(offset,limit)
    sponsors=db.scalars(select(Sponsor).order_by(Sponsor.created_at.desc(),Sponsor.id).offset(offset).limit(limit+1)).all()
    result=[]
    for sponsor in sponsors[:limit]:
        tasks=[]
        for task in db.scalars(select(SponsorTask).where(SponsorTask.sponsor_id==sponsor.id).order_by(SponsorTask.created_at.desc(),SponsorTask.id).limit(21)):
            counts=dict(db.execute(select(TaskApplication.status,func.count()).where(TaskApplication.task_id==task.id).group_by(TaskApplication.status)).all())
            participants=db.scalar(select(func.count(func.distinct(TaskApplication.user_id))).where(TaskApplication.task_id==task.id))
            tasks.append({**task_dict(task),'applications':counts,'participants':participants})
        result.append({**sponsor_dict(sponsor),'tasks':tasks[:20],'tasks_has_more':len(tasks)>20})
    return {'items':result,'has_more':len(sponsors)>limit}

@router.post('/api/admin/sponsors')
def create_sponsor(data:SponsorCreate,db:DB,admin:Admin):
    owner(admin);operation_lock(db,'sponsor',admin.id,data.request_key)
    existing=db.scalar(select(Sponsor).where(Sponsor.created_by==admin.id,Sponsor.request_key==data.request_key))
    values=data.model_dump(exclude={'reason','request_key'})
    original=fingerprint(data.model_dump(exclude={'request_key'}))
    if existing:
        if existing.request_fingerprint!=original:raise HTTPException(409,'Повтор создания должен содержать те же данные')
        return sponsor_dict(existing)
    sponsor=Sponsor(created_by=admin.id,request_key=data.request_key,request_fingerprint=original,**values)
    db.add(sponsor);db.flush()
    db.add(Audit(actor_id=admin.id,action='SPONSOR_CREATED',target=sponsor.id,reason=data.reason))
    db.commit();return sponsor_dict(sponsor)

@router.put('/api/admin/sponsors/{sponsor_id}')
def edit_sponsor(sponsor_id:str,data:SponsorData,db:DB,admin:Admin):
    owner(admin)
    sponsor=db.scalar(select(Sponsor).where(Sponsor.id==sponsor_id).with_for_update())
    if not sponsor:raise HTTPException(404,'Спонсор не найден')
    old=sponsor_dict(sponsor)
    for key,value in data.model_dump(exclude={'reason'}).items():setattr(sponsor,key,value)
    sponsor.updated_at=int(time.time())
    db.add(Audit(actor_id=admin.id,action='SPONSOR_UPDATED',target=sponsor.id,
                 reason=json.dumps({'reason':data.reason,'before':old,'after':sponsor_dict(sponsor)},ensure_ascii=False)))
    db.commit();return sponsor_dict(sponsor)

@router.post('/api/admin/sponsors/{sponsor_id}/tasks')
def create_task(sponsor_id:str,data:TaskCreate,db:DB,admin:Admin):
    owner(admin);operation_lock(db,'task',admin.id,data.request_key)
    existing=db.scalar(select(SponsorTask).where(SponsorTask.created_by==admin.id,SponsorTask.request_key==data.request_key))
    values=data.model_dump(exclude={'reason','request_key'})
    original=fingerprint({'sponsor_id':sponsor_id,**data.model_dump(exclude={'request_key'})})
    if existing:
        if existing.request_fingerprint!=original:raise HTTPException(409,'Повтор создания задания должен содержать те же данные')
        return task_dict(existing)
    sponsor=db.scalar(select(Sponsor).where(Sponsor.id==sponsor_id).with_for_update())
    if not sponsor:raise HTTPException(404,'Спонсор не найден')
    if data.deadline_at<=int(time.time()):raise HTTPException(422,'Срок задания должен быть в будущем')
    task=SponsorTask(sponsor_id=sponsor_id,created_by=admin.id,request_key=data.request_key,request_fingerprint=original,**values)
    db.add(task);db.flush()
    db.add(Audit(actor_id=admin.id,action='TASK_CREATED',target=task.id,reason=data.reason))
    db.commit();return task_dict(task)

@router.put('/api/admin/tasks/{task_id}')
def edit_task(task_id:str,data:TaskData,db:DB,admin:Admin):
    owner(admin)
    target=db.get(SponsorTask,task_id)
    if not target:raise HTTPException(404,'Задание не найдено')
    db.scalar(select(Sponsor).where(Sponsor.id==target.sponsor_id).with_for_update())
    task=db.scalar(select(SponsorTask).where(SponsorTask.id==task_id).with_for_update().execution_options(populate_existing=True))
    values=data.model_dump(exclude={'reason'})
    if db.scalar(select(TaskApplication.id).where(TaskApplication.task_id==task_id).limit(1)):
        if any(getattr(task,k)!=v for k,v in values.items() if k!='active'):
            raise HTTPException(409,'После первой заявки условия, награда и срок не меняются. Можно только отключить задание.')
    elif data.active and data.deadline_at<=int(time.time()):raise HTTPException(422,'Срок активного задания должен быть в будущем')
    before=task_dict(task)
    for key,value in values.items():setattr(task,key,value)
    task.updated_at=int(time.time())
    db.add(Audit(actor_id=admin.id,action='TASK_UPDATED',target=task.id,
                 reason=json.dumps({'reason':data.reason,'before':before,'after':task_dict(task)},ensure_ascii=False)))
    db.commit();return task_dict(task)

@router.post('/api/tasks/{task_id}/applications')
def apply(task_id:str,data:ApplicationData,db:DB,user:CurrentUser):
    participant=db.scalar(select(User).where(User.id==user.id).with_for_update().execution_options(populate_existing=True))
    active(participant)
    existing=db.scalar(select(TaskApplication).where(TaskApplication.user_id==user.id,TaskApplication.request_key==data.request_key))
    if existing:
        if (existing.task_id,existing.evidence,existing.evidence_url,existing.terms_hash)!=(task_id,data.evidence,data.evidence_url,data.terms_hash):
            raise HTTPException(409,'Повтор заявки должен содержать те же доказательства')
        return application_dict(existing)
    target=db.get(SponsorTask,task_id)
    if not target:raise HTTPException(404,'Задание не найдено')
    sponsor=db.scalar(select(Sponsor).where(Sponsor.id==target.sponsor_id).with_for_update())
    task=db.scalar(select(SponsorTask).where(SponsorTask.id==task_id).with_for_update().execution_options(populate_existing=True))
    if not sponsor.active or not task.active:raise HTTPException(409,'Задание сейчас недоступно')
    if task.deadline_at<=int(time.time()):raise HTTPException(409,'Срок выполнения задания истёк')
    if data.terms_hash!=task_terms(task):raise HTTPException(409,'Условия задания изменились. Обновите список и прочитайте задание заново.')
    last=db.scalar(select(TaskApplication).where(TaskApplication.task_id==task_id,TaskApplication.user_id==user.id).order_by(TaskApplication.attempt.desc()).limit(1))
    if last and last.status in ('PENDING','APPROVED'):raise HTTPException(409,'Заявка уже на проверке или награда получена')
    application=TaskApplication(task_id=task.id,user_id=user.id,request_key=data.request_key,
          attempt=(last.attempt+1 if last else 1),task_title=task.title,sponsor_name=sponsor.name,
          conditions_snapshot=task.conditions,reward_points=task.reward_points,deadline_at=task.deadline_at,
          terms_hash=data.terms_hash,evidence=data.evidence,evidence_url=data.evidence_url)
    db.add(application);db.commit();return application_dict(application)

@router.get('/api/me/task-applications')
def own_applications(db:DB,user:CurrentUser,offset:int=0,limit:int=30):
    page(offset,limit)
    rows=db.scalars(select(TaskApplication).where(TaskApplication.user_id==user.id)
           .order_by(TaskApplication.created_at.desc(),TaskApplication.attempt.desc(),TaskApplication.id)
           .offset(offset).limit(limit+1)).all()
    return {'items':[application_dict(a) for a in rows[:limit]],'has_more':len(rows)>limit}

@router.get('/api/admin/task-applications')
def review_applications(db:DB,admin:Admin,status:Literal['PENDING','APPROVED','REJECTED']='PENDING',offset:int=0,limit:int=30):
    owner(admin);page(offset,limit)
    rows=db.execute(select(TaskApplication,User).join(User,User.id==TaskApplication.user_id)
           .where(TaskApplication.status==status).order_by(TaskApplication.created_at,TaskApplication.id)
           .offset(offset).limit(limit+1)).all()
    return {'items':[{**application_dict(a),'name':u.name,'user_id':u.id,'frozen':u.frozen} for a,u in rows[:limit]],'has_more':len(rows)>limit}

@router.post('/api/admin/task-applications/{application_id}/decision')
def decide_application(application_id:str,data:ApplicationDecision,db:DB,admin:Admin):
    owner(admin)
    target=db.get(TaskApplication,application_id)
    if not target:raise HTTPException(404,'Заявка не найдена')
    participant=db.scalar(select(User).where(User.id==target.user_id).with_for_update())
    task_info=db.get(SponsorTask,target.task_id)
    db.scalar(select(Sponsor).where(Sponsor.id==task_info.sponsor_id).with_for_update())
    db.scalar(select(SponsorTask).where(SponsorTask.id==task_info.id).with_for_update())
    application=db.scalar(select(TaskApplication).where(TaskApplication.id==application_id).with_for_update().execution_options(populate_existing=True))
    if application.status!='PENDING':
        if (application.status,application.reviewed_by,application.review_reason)==(data.decision,admin.id,data.reason):return application_dict(application)
        raise HTTPException(409,'По заявке уже принято решение')
    if data.decision=='APPROVED':
        active(participant)
        # Terms were validated and snapshotted on submission. Closing a task or
        # reaching its deadline does not cancel an on-time pending application.
        event_key=f'task:{application.task_id}:{application.user_id}'
        if db.scalar(select(Points.id).where(Points.event_key==event_key)):raise HTTPException(409,'Награда за это задание уже начислена')
        db.add(Points(user_id=participant.id,event_key=event_key,delta=application.reward_points,
                      reason=f'Задание «{application.task_title}» · {application.sponsor_name}'))
    application.status=data.decision;application.review_reason=data.reason
    application.reviewed_by=admin.id;application.reviewed_at=int(time.time())
    db.add(Audit(actor_id=admin.id,action='TASK_APPLICATION_'+data.decision,target=application.id,
          reason=json.dumps({'reason':data.reason,'points':application.reward_points if data.decision=='APPROVED' else 0,'user_id':participant.id},ensure_ascii=False)))
    db.commit();return application_dict(application)


@router.get('/api/sponsors/{sponsor_id}/tasks')
def sponsor_tasks(sponsor_id:str,db:DB,offset:int=0,limit:int=20):
    page(offset,limit)
    sponsor=db.get(Sponsor,sponsor_id)
    if not sponsor or not sponsor.active:raise HTTPException(404,'Спонсор не найден')
    rows=db.scalars(select(SponsorTask).where(SponsorTask.sponsor_id==sponsor_id,SponsorTask.active==True,
          SponsorTask.deadline_at>int(time.time())).order_by(SponsorTask.deadline_at,SponsorTask.id).offset(offset).limit(limit+1)).all()
    return {'items':[task_dict(t) for t in rows[:limit]],'has_more':len(rows)>limit}

@router.get('/api/admin/sponsors/{sponsor_id}/tasks')
def managed_tasks(sponsor_id:str,db:DB,admin:Admin,offset:int=0,limit:int=20):
    owner(admin);page(offset,limit)
    if not db.get(Sponsor,sponsor_id):raise HTTPException(404,'Спонсор не найден')
    rows=db.scalars(select(SponsorTask).where(SponsorTask.sponsor_id==sponsor_id)
         .order_by(SponsorTask.created_at.desc(),SponsorTask.id).offset(offset).limit(limit+1)).all()
    result=[]
    for t in rows[:limit]:
        counts=dict(db.execute(select(TaskApplication.status,func.count()).where(TaskApplication.task_id==t.id).group_by(TaskApplication.status)).all())
        participants=db.scalar(select(func.count(func.distinct(TaskApplication.user_id))).where(TaskApplication.task_id==t.id))
        result.append({**task_dict(t),'applications':counts,'participants':participants})
    return {'items':result,'has_more':len(rows)>limit}

@router.get('/api/me/task-statuses')
def task_statuses(db:DB,user:CurrentUser):
    latest=select(TaskApplication.id,func.row_number().over(partition_by=TaskApplication.task_id,order_by=TaskApplication.attempt.desc()).label('position')).where(TaskApplication.user_id==user.id).subquery()
    rows=db.scalars(select(TaskApplication).join(latest,latest.c.id==TaskApplication.id).where(latest.c.position==1)).all()
    return [dict(id=a.id,task_id=a.task_id,status=a.status,review_reason=a.review_reason,reward_points=a.reward_points) for a in rows]
