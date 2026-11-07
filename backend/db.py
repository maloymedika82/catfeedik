import os
import time
import uuid
from sqlalchemy import create_engine, event, ForeignKey, UniqueConstraint, String, BigInteger, Float, Boolean, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

class Base(DeclarativeBase):
    pass

def uid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100), default='')
    language: Mapped[str] = mapped_column(String(2), default='ru')
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String, default='USER')
    wallet: Mapped[str] = mapped_column(String(200), default='')
    created_at: Mapped[int] = mapped_column(BigInteger, default=lambda: int(time.time()))

class Session(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    expires_at: Mapped[int] = mapped_column(BigInteger)

class Feeding(Base):
    __tablename__ = 'feedings'
    __table_args__ = (UniqueConstraint('user_id', 'request_key'),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    request_key: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String, default='UPLOADING', index=True)
    city: Mapped[str] = mapped_column(String(100))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    accuracy: Mapped[float] = mapped_column(Float)
    mime_type: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(BigInteger)
    object_key: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=lambda: int(time.time()))
    claimed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    decision_reason: Mapped[str] = mapped_column(Text, default='')

class Points(Base):
    __tablename__ = 'points_ledger'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    event_key: Mapped[str] = mapped_column(String, unique=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(BigInteger, default=lambda: int(time.time()))

class Audit(Base):
    __tablename__ = 'admin_logs'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String)
    target: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(BigInteger, default=lambda: int(time.time()))

class Leaderboard(Base):
    __tablename__ = 'leaderboard_snapshots'
    __table_args__ = (UniqueConstraint('hour', 'user_id'),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    hour: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    rank: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer)
    feedings: Mapped[int] = mapped_column(Integer)

url = os.getenv('DATABASE_URL', 'sqlite:///./.local/catfeedik.db')
if url.startswith('sqlite:'):
    os.makedirs('.local', exist_ok=True)
engine = create_engine(url, connect_args={'check_same_thread': False} if url.startswith('sqlite:') else {}, pool_pre_ping=True)
if url.startswith('sqlite:'):
    @event.listens_for(engine, 'connect')
    def sqlite_pragmas(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=5000')
SessionLocal = sessionmaker(engine, expire_on_commit=False)

def get_db():
    with SessionLocal() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise

class SnapshotRun(Base):
    __tablename__ = 'leaderboard_runs'
    hour: Mapped[int] = mapped_column(BigInteger,primary_key=True)

class VideoAsset(Base):
    __tablename__ = 'video_assets'
    feeding_id: Mapped[str] = mapped_column(ForeignKey('feedings.id'),primary_key=True)
    status: Mapped[str] = mapped_column(String,default='PENDING',index=True)
    city_id: Mapped[str] = mapped_column(String,default='',index=True)
    output_key: Mapped[str] = mapped_column(String,default='')
    poster_key: Mapped[str] = mapped_column(String,default='')
    source_hash: Mapped[str] = mapped_column(String,default='',index=True)
    duration: Mapped[float] = mapped_column(Float,default=0)
    attempts: Mapped[int] = mapped_column(Integer,default=0)
    lease: Mapped[str] = mapped_column(String,default='')
    updated_at: Mapped[int] = mapped_column(BigInteger,default=lambda:int(time.time()))
    reason: Mapped[str] = mapped_column(Text,default='')
    flags: Mapped[str] = mapped_column(Text,default='[]')

class AICheck(Base):
    __tablename__ = 'ai_checks'
    feeding_id: Mapped[str] = mapped_column(ForeignKey('feedings.id'),primary_key=True)
    status: Mapped[str] = mapped_column(String,default='NOT_CONFIGURED')
    decision: Mapped[str] = mapped_column(String,default='REVIEW')
    model: Mapped[str] = mapped_column(String,default='')
    confidence: Mapped[float] = mapped_column(Float,default=0)
    reason: Mapped[str] = mapped_column(Text,default='')
    attempts: Mapped[int] = mapped_column(Integer,default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger,default=lambda:int(time.time()))

class Like(Base):
    __tablename__ = 'likes'
    feeding_id: Mapped[str] = mapped_column(ForeignKey('feedings.id'),primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'),primary_key=True)
    created_at: Mapped[int] = mapped_column(BigInteger,default=lambda:int(time.time()))

class AIRetry(Base):
    __tablename__ = 'ai_retry_schedule'
    feeding_id: Mapped[str] = mapped_column(ForeignKey('feedings.id'),primary_key=True)
    not_before: Mapped[int] = mapped_column(BigInteger,default=0,index=True)
    category: Mapped[str] = mapped_column(String,default='')
    http_status: Mapped[int] = mapped_column(Integer,default=0)

class ProviderGate(Base):
    __tablename__ = 'ai_provider_gates'
    scope: Mapped[str] = mapped_column(String,primary_key=True)
    next_request_at: Mapped[int] = mapped_column(BigInteger,default=0)

class RuntimeControl(Base):
    __tablename__ = 'runtime_controls'
    name: Mapped[str] = mapped_column(String,primary_key=True)
    value: Mapped[str] = mapped_column(String)

class Appeal(Base):
    __tablename__ = 'appeals'
    id: Mapped[str] = mapped_column(String,primary_key=True,default=uid)
    feeding_id: Mapped[str] = mapped_column(ForeignKey('feedings.id'),unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'),index=True)
    original_reviewer: Mapped[str | None] = mapped_column(ForeignKey('users.id'),nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'),nullable=True)
    status: Mapped[str] = mapped_column(String,default='OPEN',index=True)
    reason: Mapped[str] = mapped_column(Text)
    decision_reason: Mapped[str] = mapped_column(Text,default='')
    created_at: Mapped[int] = mapped_column(BigInteger,default=lambda:int(time.time()))
    resolved_at: Mapped[int | None] = mapped_column(BigInteger,nullable=True)

class PointAdjustment(Base):
    __tablename__ = 'point_adjustments'
    __table_args__ = (UniqueConstraint('actor_id','request_key'),)
    id: Mapped[str] = mapped_column(String,primary_key=True,default=uid)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'),index=True)
    request_key: Mapped[str] = mapped_column(String(80))
    delta: Mapped[int] = mapped_column(Integer)
    old_balance: Mapped[int] = mapped_column(Integer)
    new_balance: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(BigInteger,default=lambda:int(time.time()))

class Sponsor(Base):
    __tablename__ = 'sponsors'
    __table_args__ = (UniqueConstraint('created_by','request_key'),)
    id: Mapped[str] = mapped_column(String,primary_key=True,default=uid)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    request_key: Mapped[str] = mapped_column(String(80))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    logo_url: Mapped[str] = mapped_column(String(2048),default='')
    active: Mapped[bool] = mapped_column(Boolean,default=False,index=True)
    created_at: Mapped[int] = mapped_column(BigInteger,default=lambda:int(time.time()))
    updated_at: Mapped[int] = mapped_column(BigInteger,default=lambda:int(time.time()))

class SponsorTask(Base):
    __tablename__ = 'sponsor_tasks'
    __table_args__ = (UniqueConstraint('created_by','request_key'),)
    id: Mapped[str] = mapped_column(String,primary_key=True,default=uid)
    sponsor_id: Mapped[str] = mapped_column(ForeignKey('sponsors.id'),index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    request_key: Mapped[str] = mapped_column(String(80))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(150))
    conditions: Mapped[str] = mapped_column(Text)
    reward_points: Mapped[int] = mapped_column(Integer)
    deadline_at: Mapped[int] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean,default=False,index=True)
    created_at: Mapped[int] = mapped_column(BigInteger,default=lambda:int(time.time()))
    updated_at: Mapped[int] = mapped_column(BigInteger,default=lambda:int(time.time()))

class TaskApplication(Base):
    __tablename__ = 'task_applications'
    __table_args__ = (UniqueConstraint('user_id','request_key'),UniqueConstraint('task_id','user_id','attempt'))
    id: Mapped[str] = mapped_column(String,primary_key=True,default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey('sponsor_tasks.id'),index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'),index=True)
    request_key: Mapped[str] = mapped_column(String(80))
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String,default='PENDING',index=True)
    task_title: Mapped[str] = mapped_column(String(150))
    sponsor_name: Mapped[str] = mapped_column(String(120))
    conditions_snapshot: Mapped[str] = mapped_column(Text)
    reward_points: Mapped[int] = mapped_column(Integer)
    deadline_at: Mapped[int] = mapped_column(BigInteger)
    terms_hash: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[str] = mapped_column(Text)
    evidence_url: Mapped[str] = mapped_column(String(2048),default='')
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'),nullable=True)
    review_reason: Mapped[str] = mapped_column(Text,default='')
    created_at: Mapped[int] = mapped_column(BigInteger,default=lambda:int(time.time()))
    reviewed_at: Mapped[int | None] = mapped_column(BigInteger,nullable=True)

class ParticipationConsent(Base):
    __tablename__ = 'participation_consents'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'),primary_key=True)
    version: Mapped[str] = mapped_column(String(40),primary_key=True)
    document_hash: Mapped[str] = mapped_column(String(64))
    accepted_at: Mapped[int] = mapped_column(BigInteger,default=lambda:int(time.time()))
