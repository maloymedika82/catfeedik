"""Versioned participation notice and explicit, account-scoped acceptance."""
import hashlib
import json
import time
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,ConfigDict,StrictBool
from sqlalchemy import select
from .db import ParticipationConsent,User
from .dependencies import DB,CurrentUser,active

VERSION='2026-11-07.1'
PARAGRAPHS=[
    'Catfeedik помогает делиться кормлениями бездомных кошек и собак. Снимайте настоящее кормление, не причиняйте вред животным и не загружайте чужие или повторные записи. Видео — до 15 секунд, без пауз.',
    'Для участия используем подтверждённый Telegram-профиль: идентификатор, имя и язык. Камера и микрофон нужны для записи видео со звуком. Доступ запрашивается при открытии камеры; в фоне запись не ведётся.',
    'Геолокация нужна при подготовке кормления: координаты и точность передаются серверу для проверки места и защиты от повторных кормлений. Постоянного отслеживания нет. На публичной карте показываем центр ближайшего города, а не точные координаты кормления.',
    'Отправленное видео и данные проверки хранятся на сервере приложения и доступны для модерации. Кадры видео могут передаваться внешнему AI-провайдеру через AnyModel для проверки кормления. При недоступности AI возможна ручная проверка.',
    'После одобрения нормализованное видео со звуком публикуется в городской ленте; имя профиля, город и результаты участия могут отображаться в рейтинге. Не снимайте людей без их согласия, документы, адреса и другие личные данные. Не отправляйте материал, который не хотите публиковать.',
    'Поинты начисляются после подтверждения, не за одну отправку. Недостоверные материалы могут быть отклонены, аккаунт — заморожен. Для отклонённого кормления предусмотрена апелляция. Денежные выплаты и денежные обязательства сейчас отключены.',
    'Можно отказаться от участия и продолжить просмотр карты. До отправки можно закрыть запись; при закрытии несохранённое видео удаляется из текущей сессии. Согласие с этими условиями не выдаёт системных разрешений: ими отдельно управляют Telegram, браузер и настройки телефона.'
]
DOCUMENT_HASH=hashlib.sha256(json.dumps(PARAGRAPHS,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
router=APIRouter()

def document():
    return {'version':VERSION,'document_hash':DOCUMENT_HASH,'title':'Условия участия и использование данных','paragraphs':PARAGRAPHS}

def accepted(db,user_id):
    row=db.get(ParticipationConsent,(user_id,VERSION))
    return row if row and row.document_hash==DOCUMENT_HASH else None

def require_consent(db,user_id):
    if not accepted(db,user_id):raise HTTPException(409,'Перед отправкой кормления прочитайте и примите актуальные условия участия.')

@router.get('/api/participation-terms')
def public_terms():return document()

@router.get('/api/me/participation-consent')
def current_consent(db:DB,user:CurrentUser):
    row=accepted(db,user.id)
    return {**document(),'accepted':bool(row),'accepted_at':row.accepted_at if row else None}

class Acceptance(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:str
    document_hash:str
    accepted:StrictBool

@router.post('/api/me/participation-consent')
def accept(data:Acceptance,db:DB,user:CurrentUser):
    active(user)
    if not data.accepted:raise HTTPException(422,'Требуется явное согласие')
    if data.version!=VERSION or data.document_hash!=DOCUMENT_HASH:raise HTTPException(409,'Условия обновились. Откройте их заново перед согласием.')
    participant=db.scalar(select(User).where(User.id==user.id).with_for_update().execution_options(populate_existing=True))
    active(participant)
    row=accepted(db,user.id)
    if not row:
        row=db.get(ParticipationConsent,(user.id,VERSION))
        if row:row.document_hash=DOCUMENT_HASH;row.accepted_at=int(time.time())
        else:row=ParticipationConsent(user_id=user.id,version=VERSION,document_hash=DOCUMENT_HASH);db.add(row)
        db.commit()
    return {**document(),'accepted':True,'accepted_at':row.accepted_at}
