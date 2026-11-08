"""Telegram avatar, notification preference, and durable delivery queue.

Revision ID: 8f31c2a6d9e4
Revises: 45778a076fab
"""
from alembic import op
import sqlalchemy as sa

revision = '8f31c2a6d9e4'
down_revision = '45778a076fab'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('photo_url', sa.String(length=2048), nullable=False, server_default=''))
    op.add_column('users', sa.Column('notify_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table('notifications',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('event_key', sa.String(length=160), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('feeding_id', sa.String(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.BigInteger(), nullable=False),
        sa.Column('claimed_at', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.Column('sent_at', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['feeding_id'], ['feedings.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_key'))
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('ix_notifications_status', 'notifications', ['status'])


def downgrade():
    op.drop_index('ix_notifications_status', table_name='notifications')
    op.drop_index('ix_notifications_user_id', table_name='notifications')
    op.drop_table('notifications')
    op.drop_column('users', 'notify_enabled')
    op.drop_column('users', 'photo_url')
