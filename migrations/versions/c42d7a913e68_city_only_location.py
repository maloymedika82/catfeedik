"""Replace precise feeding coordinates with catalogue city centres.

Revision ID: c42d7a913e68
Revises: 8f31c2a6d9e4
"""
from alembic import op
import sqlalchemy as sa
from backend.geography import city_info, nearest_city

revision = 'c42d7a913e68'
down_revision = '8f31c2a6d9e4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('feedings', sa.Column('city_id', sa.String(length=20), nullable=False, server_default=''))
    op.add_column('video_assets', sa.Column('fingerprint', sa.Text(), nullable=False, server_default='[]'))
    connection=op.get_bind()
    rows=connection.execute(sa.text('SELECT id, latitude, longitude FROM feedings')).all()
    for feeding_id,latitude,longitude in rows:
        place=nearest_city(latitude,longitude)
        connection.execute(sa.text('UPDATE feedings SET city_id=:city_id, city=:city, latitude=:latitude, longitude=:longitude, accuracy=0 WHERE id=:id'),
                           {'city_id':place['id'],'city':place['label'],'latitude':place['latitude'],
                            'longitude':place['longitude'],'id':feeding_id})
    op.create_index('ix_feedings_city_id', 'feedings', ['city_id'])


def downgrade():
    op.drop_column('video_assets', 'fingerprint')
    op.drop_index('ix_feedings_city_id', table_name='feedings')
    op.drop_column('feedings', 'city_id')
