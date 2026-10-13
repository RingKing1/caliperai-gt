"""Frame-level image embeddings for semantic scene search (CLIP).

Revision ID: 037
Revises: 036
Create Date: 2026-10-13
"""
from alembic import op


revision = '037'
down_revision = '036'
branch_labels = None
depends_on = None


TABLE = 'frame_image_embeddings'


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.execute(
        f"""
        CREATE TABLE {TABLE} (
            id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
            frame_id uuid NOT NULL REFERENCES frames(id) ON DELETE CASCADE,
            camera varchar(32) NOT NULL,
            model varchar(64) NOT NULL,
            embedding vector(512) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (frame_id, camera, model)
        )
        """
    )
    op.execute(
        f"CREATE INDEX ix_{TABLE}_frame_id ON {TABLE} (frame_id)"
    )
    op.execute(
        f"""
        CREATE INDEX ix_{TABLE}_embedding_hnsw
        ON {TABLE} USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
