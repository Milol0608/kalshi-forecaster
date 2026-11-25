"""maker orders: edge, through-volume and filled contracts for the Kelly arms (ADR 0007)

Revision ID: a7d1c0f3e2b1
Revises: d8333c63b71c
Create Date: 2026-11-25 15:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7d1c0f3e2b1'
down_revision: Union[str, Sequence[str], None] = 'd8333c63b71c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('maker_orders', sa.Column('edge', sa.Numeric(precision=8, scale=4), nullable=True))
    op.add_column('maker_orders', sa.Column('thru_volume', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('maker_orders', sa.Column('filled_contracts', sa.Numeric(precision=18, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column('maker_orders', 'filled_contracts')
    op.drop_column('maker_orders', 'thru_volume')
    op.drop_column('maker_orders', 'edge')
