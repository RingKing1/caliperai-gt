"""Reconcile Alembic schema with the current ORM models

Revision ID: 039
Revises: 038
Create Date: 2026-10-15

Historically the app provisioned its schema with ``create_all`` at startup
while Alembic migrations existed in parallel, so the migration chain drifted
from the models. This migration closes the drift so a fresh database reaches
the current application schema with ``alembic upgrade head`` alone.

Every statement is idempotent, making it safe on databases provisioned by
either path (create_all or Alembic). Obsolete migration-era columns/indexes
are kept (non-destructive); only structures the current ORM needs but the
chain was missing are added.

Changes:
- annotations.type/source: legacy PG enums -> VARCHAR(30/50), matching the
  ORM String columns (the enum labels predate annotation types/sources used
  by the app today, e.g. segmentation_2d / auto_interpolated);
- audit_logs.created_at -> timestamp (+ index renames) matching the ORM;
- segmentation_blobs: add current ORM columns (blob_data/blob_url/compression/
  point_count/checksum/updated_at); legacy 001 columns retained;
- add indexes the ORM creates but the chain lacked (notably the
  frames(scene_id, frame_index) unique index).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # 1. annotations: drop legacy PG enums, align column types with the ORM.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'annotationtype') THEN
                ALTER TABLE annotations
                    ALTER COLUMN type TYPE VARCHAR(30) USING type::text;
                DROP TYPE annotationtype;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'annotationsource') THEN
                -- The 001 default ('manual'::annotationsource) depends on the
                -- enum type; the ORM column has no server-side default.
                ALTER TABLE annotations ALTER COLUMN source DROP DEFAULT;
                ALTER TABLE annotations
                    ALTER COLUMN source TYPE VARCHAR(50) USING source::text;
                DROP TYPE annotationsource;
            END IF;
        END $$;
        """
    )

    # 2. audit_logs.created_at -> "timestamp" (ORM AuditLog.timestamp).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'audit_logs' AND column_name = 'timestamp'
            )
            AND EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'audit_logs' AND column_name = 'created_at'
            ) THEN
                ALTER TABLE audit_logs RENAME COLUMN created_at TO "timestamp";
            END IF;
        END $$;
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_created_at")
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_entity_type_entity_id")
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_audit_logs_timestamp '
        'ON audit_logs ("timestamp")'
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_entity "
        "ON audit_logs (entity_type, entity_id)"
    )

    # 3. segmentation_blobs: current ORM shape (legacy 001 columns retained).
    blob_columns = {
        "blob_data": "ADD COLUMN blob_data BYTEA",
        "blob_url": "ADD COLUMN blob_url VARCHAR(500)",
    }
    for column, ddl in blob_columns.items():
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'segmentation_blobs' AND column_name = '{column}'
                ) THEN
                    ALTER TABLE segmentation_blobs {ddl};
                END IF;
            END $$;
            """
        )
    # NOT NULL columns need a temporary default to survive any legacy rows.
    not_null_adds = {
        "compression": ("VARCHAR(20)", "'zlib'"),
        "point_count": ("INTEGER", "0"),
        "checksum": ("VARCHAR(64)", "''"),
        "updated_at": ("TIMESTAMP WITH TIME ZONE", "now()"),
    }
    for column, (column_type, default_sql) in not_null_adds.items():
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'segmentation_blobs' AND column_name = '{column}'
                ) THEN
                    ALTER TABLE segmentation_blobs
                        ADD COLUMN {column} {column_type}
                        NOT NULL DEFAULT {default_sql};
                END IF;
            END $$;
            """
        )
    # The ORM has Python-side defaults only; mirror create_all and drop DB defaults.
    op.execute("ALTER TABLE segmentation_blobs ALTER COLUMN compression DROP DEFAULT")
    op.execute("ALTER TABLE segmentation_blobs ALTER COLUMN point_count DROP DEFAULT")
    op.execute("ALTER TABLE segmentation_blobs ALTER COLUMN checksum DROP DEFAULT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_segmentation_blobs_annotation_id "
        "ON segmentation_blobs (annotation_id)"
    )

    # 4. frame_image_embeddings lives only in migration 037 (no ORM table);
    # ensure it exists for databases provisioned via create_all + stamp.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS frame_image_embeddings (
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
        "CREATE INDEX IF NOT EXISTS ix_frame_image_embeddings_frame_id "
        "ON frame_image_embeddings (frame_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_frame_image_embeddings_embedding_hnsw "
        "ON frame_image_embeddings USING hnsw (embedding vector_cosine_ops)"
    )

    # 5. Indexes declared by the ORM but missing from the migration chain.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_annotations_attributes "
        "ON annotations USING gin (attributes)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_annotations_type ON annotations (type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_campaigns_created_at ON campaigns (created_at)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_datasets_name ON datasets (name)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_frames_frame_index ON frames (frame_index)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_frames_scene_id ON frames (scene_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_frame_scene_index "
        "ON frames (scene_id, frame_index)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_scenes_name ON scenes (name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_priority ON tasks (priority)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_stage ON tasks (stage)")


def downgrade() -> None:
    # Reconciliation migration: structural alignment is not reversed; legacy
    # columns/indexes/enums are intentionally left untouched on downgrade.
    pass
