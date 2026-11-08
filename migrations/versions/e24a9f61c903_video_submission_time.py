"""Record video submission time for the hourly participation limit.

Revision ID: e24a9f61c903
Revises: d671b48a9c02
"""
from alembic import op
import sqlalchemy as sa

revision = 'e24a9f61c903'
down_revision = 'd671b48a9c02'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('feedings',sa.Column('submitted_at',sa.BigInteger(),nullable=False,server_default='0'))
    op.execute(sa.text("UPDATE feedings SET submitted_at=created_at WHERE status<>'UPLOADING'"))


def downgrade():
    op.drop_column('feedings','submitted_at')
