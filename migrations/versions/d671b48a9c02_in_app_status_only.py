"""Stop bot status messages and clear the old delivery queue.

Revision ID: d671b48a9c02
Revises: c42d7a913e68
"""
from alembic import op
import sqlalchemy as sa

revision = 'd671b48a9c02'
down_revision = 'c42d7a913e68'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text('UPDATE users SET notify_enabled = false'))
    op.execute(sa.text("UPDATE notifications SET status = 'SKIPPED' WHERE status IN ('PENDING', 'SENDING', 'FAILED')"))


def downgrade():
    # Old notifications are deliberately not restored for delivery.
    pass
