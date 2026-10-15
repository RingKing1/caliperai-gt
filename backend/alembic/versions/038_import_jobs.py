"""Background dataset import jobs.

Revision ID: 038
Revises: 037
Create Date: 2026-10-15
"""
from alembic import op


revision = '038'
down_revision = '037'
branch_labels = None
depends_on = None


TABLE = 'import_jobs'


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {TABLE} (
            id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
            dataset_id uuid NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            job_type varchar(16) NOT NULL,
            source_filename varchar(512),
            status varchar(16) NOT NULL DEFAULT 'pending',
            phase varchar(32),
            progress integer NOT NULL DEFAULT 0,
            total_scenes integer NOT NULL DEFAULT 0,
            processed_scenes integer NOT NULL DEFAULT 0,
            scenes_imported integer NOT NULL DEFAULT 0,
            frames_imported integer NOT NULL DEFAULT 0,
            message text,
            options jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            staged_path text,
            result jsonb,
            error text,
            started_at timestamptz,
            finished_at timestamptz,
            heartbeat_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(f"CREATE INDEX ix_{TABLE}_dataset_id ON {TABLE}(dataset_id)")


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
