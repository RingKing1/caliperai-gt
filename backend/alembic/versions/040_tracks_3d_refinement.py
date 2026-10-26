"""Track-level refinement flags for 3D cuboids.

Revision ID: 040
Revises: 039
Create Date: 2026-10-26

Stores one row per explicitly reviewed track. Absence of a row means
"AI-only" — the flag is not derived from annotation rows, so refining a
track never touches annotations_3d (668k rows stay untouched).
"""
from alembic import op


revision = '040'
down_revision = '039'
branch_labels = None
depends_on = None


TABLE = 'tracks_3d'


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            track_id uuid PRIMARY KEY,
            task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            is_refined boolean NOT NULL DEFAULT false,
            refined_by uuid REFERENCES users(id) ON DELETE SET NULL,
            refined_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_task_id ON {TABLE}(task_id)")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_refined ON {TABLE}(task_id) "
        f"WHERE is_refined"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
