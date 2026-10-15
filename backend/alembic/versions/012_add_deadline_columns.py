"""add_deadline_columns

Revision ID: 012
Revises: 011
Create Date: 2026-02-03

Adds deadline columns to campaigns, datasets, and scenes tables.
Tasks already have a deadline column.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def _add_deadline_if_missing(table_name: str) -> None:
    # 001_initial already created these columns; guard so the migration stays
    # idempotent on databases initialised from the full chain (and still adds
    # them on older deployments that predate the columns).
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = '{table_name}' AND column_name = 'deadline'
            ) THEN
                ALTER TABLE {table_name}
                    ADD COLUMN deadline TIMESTAMP WITH TIME ZONE;
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    # Add deadline column to campaigns, datasets and scenes (idempotent).
    for table_name in ("campaigns", "datasets", "scenes"):
        _add_deadline_if_missing(table_name)


def downgrade() -> None:
    # Remove deadline columns
    op.drop_column('scenes', 'deadline')
    op.drop_column('datasets', 'deadline')
    op.drop_column('campaigns', 'deadline')
