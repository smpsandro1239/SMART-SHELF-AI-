"""Add append-only two-person external artifact disposition events."""
from alembic import op
import sqlalchemy as sa

revision = "0034_shelf_image_artifact_disposition_events"
down_revision = "0033_shelf_image_artifact_references"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_shelf_image_artifact_reference_lineage",
        "shelf_image_artifact_references",
        ["id", "shelf_image_id", "store_id"],
        unique=True,
    )
    op.create_table(
        "shelf_image_artifact_disposition_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "artifact_reference_id",
            sa.Integer(),
            sa.ForeignKey("shelf_image_artifact_references.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "shelf_image_id",
            sa.Integer(),
            sa.ForeignKey("shelf_images.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "store_id",
            sa.Integer(),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("evidence_reference", sa.String(length=500), nullable=True),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "artifact_reference_id", "sequence_number",
            name="uq_shelf_image_artifact_disposition_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_reference_id", "shelf_image_id", "store_id"],
            [
                "shelf_image_artifact_references.id",
                "shelf_image_artifact_references.shelf_image_id",
                "shelf_image_artifact_references.store_id",
            ],
            name="fk_shelf_image_artifact_disposition_reference_lineage",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("sequence_number > 0", name="ck_shelf_image_artifact_disposition_sequence_positive"),
        sa.CheckConstraint(
            "event_type IN ('PROPOSED', 'APPROVED', 'REJECTED', 'DISPOSAL_ATTESTED')",
            name="ck_shelf_image_artifact_disposition_event_type",
        ),
        sa.CheckConstraint(
            "evidence_sha256 IS NULL OR length(evidence_sha256) = 64",
            name="ck_shelf_image_artifact_disposition_evidence_sha256_length",
        ),
    )
    op.create_index(
        "ix_shelf_image_artifact_disposition_events_shelf_image_id",
        "shelf_image_artifact_disposition_events",
        ["shelf_image_id"],
    )
    op.create_index(
        "ix_shelf_image_artifact_disposition_events_store_id",
        "shelf_image_artifact_disposition_events",
        ["store_id"],
    )
    op.create_index(
        "ix_shelf_image_artifact_disposition_artifact_created",
        "shelf_image_artifact_disposition_events",
        ["artifact_reference_id", "created_at"],
    )
    op.create_index(
        "ix_shelf_image_artifact_disposition_store_image",
        "shelf_image_artifact_disposition_events",
        ["store_id", "shelf_image_id"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION validate_shelf_image_artifact_reference_store()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM shelf_images si
                    JOIN shelves sh ON sh.id = si.shelf_id
                    JOIN zones z ON z.id = sh.zone_id
                    WHERE si.id = NEW.shelf_image_id
                      AND z.store_id = NEW.store_id
                ) THEN
                    RAISE EXCEPTION 'artifact reference store does not match shelf image lineage'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_reference_store
            BEFORE INSERT ON shelf_image_artifact_references
            FOR EACH ROW EXECUTE FUNCTION validate_shelf_image_artifact_reference_store()
        """)
        op.execute("""
            CREATE FUNCTION validate_shelf_image_artifact_disposition_event()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE
                previous_event_type VARCHAR(24);
                previous_actor_user_id INTEGER;
                actor_is_admin BOOLEAN;
                expected_sequence INTEGER;
            BEGIN
                PERFORM 1
                FROM shelf_image_artifact_references
                WHERE id = NEW.artifact_reference_id
                FOR UPDATE;

                SELECT COALESCE(MAX(sequence_number), 0) + 1
                INTO expected_sequence
                FROM shelf_image_artifact_disposition_events
                WHERE artifact_reference_id = NEW.artifact_reference_id;

                IF NEW.sequence_number <> expected_sequence THEN
                    RAISE EXCEPTION 'artifact disposition sequence must be the next sequence number'
                        USING ERRCODE = '23514';
                END IF;

                SELECT role = 'ADMIN' AND is_active IS TRUE
                INTO actor_is_admin
                FROM users
                WHERE id = NEW.actor_user_id;

                IF NEW.actor_user_id IS NULL OR COALESCE(actor_is_admin, FALSE) IS FALSE THEN
                    RAISE EXCEPTION 'artifact disposition actor must be an active administrator'
                        USING ERRCODE = '23514';
                END IF;

                SELECT event_type, actor_user_id
                INTO previous_event_type, previous_actor_user_id
                FROM shelf_image_artifact_disposition_events
                WHERE artifact_reference_id = NEW.artifact_reference_id
                ORDER BY sequence_number DESC
                LIMIT 1;

                IF NEW.event_type = 'PROPOSED' THEN
                    IF previous_event_type IS NOT NULL AND previous_event_type <> 'REJECTED' THEN
                        RAISE EXCEPTION 'artifact disposition proposal is not valid in the current state'
                            USING ERRCODE = '23514';
                    END IF;
                    IF NEW.evidence_reference IS NOT NULL OR NEW.evidence_sha256 IS NOT NULL THEN
                        RAISE EXCEPTION 'proposal cannot include completion evidence'
                            USING ERRCODE = '23514';
                    END IF;
                ELSIF NEW.event_type IN ('APPROVED', 'REJECTED') THEN
                    IF previous_event_type IS DISTINCT FROM 'PROPOSED'
                       OR previous_actor_user_id IS NOT DISTINCT FROM NEW.actor_user_id THEN
                        RAISE EXCEPTION 'artifact disposition review requires a pending proposal and a different administrator'
                            USING ERRCODE = '23514';
                    END IF;
                    IF NEW.evidence_reference IS NOT NULL OR NEW.evidence_sha256 IS NOT NULL THEN
                        RAISE EXCEPTION 'review event cannot include completion evidence'
                            USING ERRCODE = '23514';
                    END IF;
                ELSIF NEW.event_type = 'DISPOSAL_ATTESTED' THEN
                    IF previous_event_type IS DISTINCT FROM 'APPROVED'
                       OR previous_actor_user_id IS NOT DISTINCT FROM NEW.actor_user_id THEN
                        RAISE EXCEPTION 'disposition attestation requires approval by a different administrator'
                            USING ERRCODE = '23514';
                    END IF;
                    IF NEW.evidence_reference IS NULL OR btrim(NEW.evidence_reference) = ''
                       OR NEW.evidence_sha256 IS NULL
                       OR NEW.evidence_sha256 !~ '^[0-9a-f]{64}$' THEN
                        RAISE EXCEPTION 'disposition attestation requires evidence reference and SHA-256'
                            USING ERRCODE = '23514';
                    END IF;
                ELSE
                    RAISE EXCEPTION 'unsupported artifact disposition event type'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_event_validate
            BEFORE INSERT ON shelf_image_artifact_disposition_events
            FOR EACH ROW EXECUTE FUNCTION validate_shelf_image_artifact_disposition_event()
        """)
        op.execute("""
            CREATE FUNCTION prevent_shelf_image_artifact_disposition_event_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'shelf_image_artifact_disposition_events is append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_events_append_only
            BEFORE UPDATE OR DELETE ON shelf_image_artifact_disposition_events
            FOR EACH ROW EXECUTE FUNCTION prevent_shelf_image_artifact_disposition_event_mutation()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_reference_store
            BEFORE INSERT ON shelf_image_artifact_references
            WHEN NOT EXISTS (
                SELECT 1
                FROM shelf_images si
                JOIN shelves sh ON sh.id = si.shelf_id
                JOIN zones z ON z.id = sh.zone_id
                WHERE si.id = NEW.shelf_image_id
                  AND z.store_id = NEW.store_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'artifact reference store does not match shelf image lineage');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_events_no_update
            BEFORE UPDATE ON shelf_image_artifact_disposition_events
            BEGIN SELECT RAISE(ABORT, 'shelf_image_artifact_disposition_events is append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_events_no_delete
            BEFORE DELETE ON shelf_image_artifact_disposition_events
            BEGIN SELECT RAISE(ABORT, 'shelf_image_artifact_disposition_events is append-only'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_event_validate ON shelf_image_artifact_disposition_events")
        op.execute("DROP FUNCTION IF EXISTS validate_shelf_image_artifact_disposition_event()")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_reference_store ON shelf_image_artifact_references")
        op.execute("DROP FUNCTION IF EXISTS validate_shelf_image_artifact_reference_store()")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_events_append_only ON shelf_image_artifact_disposition_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_shelf_image_artifact_disposition_event_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_event_validate")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_reference_store")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_events_no_delete")

    op.drop_index(
        "ix_shelf_image_artifact_disposition_store_image",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_index(
        "ix_shelf_image_artifact_disposition_artifact_created",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_index(
        "ix_shelf_image_artifact_disposition_events_store_id",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_index(
        "ix_shelf_image_artifact_disposition_events_shelf_image_id",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_table("shelf_image_artifact_disposition_events")
    op.drop_index(
        "uq_shelf_image_artifact_reference_lineage",
        table_name="shelf_image_artifact_references",
    )
 THEN
                        RAISE EXCEPTION 'disposition attestation requires evidence reference and SHA-256'
                            USING ERRCODE = '23514';
                    END IF;
                ELSE
                    RAISE EXCEPTION 'unsupported artifact disposition event type'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_event_validate
            BEFORE INSERT ON shelf_image_artifact_disposition_events
            FOR EACH ROW EXECUTE FUNCTION validate_shelf_image_artifact_disposition_event()
        """)
        op.execute("""
            CREATE FUNCTION prevent_shelf_image_artifact_disposition_event_mutation() LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'shelf_image_artifact_disposition_events is append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_events_append_only
            BEFORE UPDATE OR DELETE ON shelf_image_artifact_disposition_events
            FOR EACH ROW EXECUTE FUNCTION prevent_shelf_image_artifact_disposition_event_mutation()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_reference_store
            BEFORE INSERT ON shelf_image_artifact_references
            WHEN NOT EXISTS (
                SELECT 1
                FROM shelf_images si
                JOIN shelves sh ON sh.id = si.shelf_id
                JOIN zones z ON z.id = sh.zone_id
                WHERE si.id = NEW.shelf_image_id
                  AND z.store_id = NEW.store_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'artifact reference store does not match shelf image lineage');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_event_validate
            BEFORE INSERT ON shelf_image_artifact_disposition_events
            BEGIN
                SELECT CASE WHEN NEW.sequence_number <> (
                    SELECT COALESCE(MAX(sequence_number), 0) + 1
                    FROM shelf_image_artifact_disposition_events
                    WHERE artifact_reference_id = NEW.artifact_reference_id
                ) THEN RAISE(ABORT, 'artifact disposition sequence must be the next sequence number') END;

                SELECT CASE WHEN NEW.actor_user_id IS NULL OR NOT EXISTS (
                    SELECT 1 FROM users
                    WHERE id = NEW.actor_user_id AND role = 'ADMIN' AND is_active = 1
                ) THEN RAISE(ABORT, 'artifact disposition actor must be an active administrator') END;

                SELECT CASE WHEN NEW.event_type = 'PROPOSED' AND (
                    EXISTS (
                        SELECT 1 FROM shelf_image_artifact_disposition_events
                        WHERE artifact_reference_id = NEW.artifact_reference_id
                    ) AND (
                        SELECT event_type FROM shelf_image_artifact_disposition_events
                        WHERE artifact_reference_id = NEW.artifact_reference_id
                        ORDER BY sequence_number DESC LIMIT 1
                    ) <> 'REJECTED'
                ) THEN RAISE(ABORT, 'artifact disposition proposal is not valid in the current state') END;

                SELECT CASE WHEN NEW.event_type IN ('APPROVED', 'REJECTED') AND (
                    COALESCE((
                        SELECT event_type FROM shelf_image_artifact_disposition_events
                        WHERE artifact_reference_id = NEW.artifact_reference_id
                        ORDER BY sequence_number DESC LIMIT 1
                    ), '') <> 'PROPOSED'
                    OR (
                        SELECT actor_user_id FROM shelf_image_artifact_disposition_events
                        WHERE artifact_reference_id = NEW.artifact_reference_id
                        ORDER BY sequence_number DESC LIMIT 1
                    ) = NEW.actor_user_id
                ) THEN RAISE(ABORT, 'artifact disposition review requires a pending proposal and a different administrator') END;

                SELECT CASE WHEN NEW.event_type = 'DISPOSAL_ATTESTED' AND (
                    COALESCE((
                        SELECT event_type FROM shelf_image_artifact_disposition_events
                        WHERE artifact_reference_id = NEW.artifact_reference_id
                        ORDER BY sequence_number DESC LIMIT 1
                    ), '') <> 'APPROVED'
                    OR (
                        SELECT actor_user_id FROM shelf_image_artifact_disposition_events
                        WHERE artifact_reference_id = NEW.artifact_reference_id
                        ORDER BY sequence_number DESC LIMIT 1
                    ) = NEW.actor_user_id
                    OR NEW.evidence_reference IS NULL
                    OR trim(NEW.evidence_reference) = ''
                    OR NEW.evidence_sha256 IS NULL
                    OR length(NEW.evidence_sha256) <> 64
                    OR NEW.evidence_sha256 GLOB '*[^0-9a-f]*'
                ) THEN RAISE(ABORT, 'disposition attestation requires independent approval and valid evidence SHA-256') END;

                SELECT CASE WHEN NEW.event_type NOT IN ('PROPOSED', 'APPROVED', 'REJECTED', 'DISPOSAL_ATTESTED')
                    THEN RAISE(ABORT, 'unsupported artifact disposition event type') END;

                SELECT CASE WHEN NEW.event_type IN ('PROPOSED', 'APPROVED', 'REJECTED')
                    AND (NEW.evidence_reference IS NOT NULL OR NEW.evidence_sha256 IS NOT NULL)
                    THEN RAISE(ABORT, 'only final attestation may include completion evidence') END;
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_events_no_update
            BEFORE UPDATE ON shelf_image_artifact_disposition_events
            BEGIN SELECT RAISE(ABORT, 'shelf_image_artifact_disposition_events is append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_events_no_delete
            BEFORE DELETE ON shelf_image_artifact_disposition_events
            BEGIN SELECT RAISE(ABORT, 'shelf_image_artifact_disposition_events is append-only'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_reference_store ON shelf_image_artifact_references")
        op.execute("DROP FUNCTION IF EXISTS validate_shelf_image_artifact_reference_store()")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_event_validate ON shelf_image_artifact_disposition_events")
        op.execute("DROP FUNCTION IF EXISTS validate_shelf_image_artifact_disposition_event()")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_events_append_only ON shelf_image_artifact_disposition_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_shelf_image_artifact_disposition_event_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_reference_store")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_event_validate")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_events_no_delete")

    op.drop_index(
        "ix_shelf_image_artifact_disposition_store_image",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_index(
        "ix_shelf_image_artifact_disposition_artifact_created",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_index(
        "ix_shelf_image_artifact_disposition_events_store_id",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_index(
        "ix_shelf_image_artifact_disposition_events_shelf_image_id",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_table("shelf_image_artifact_disposition_events")
    op.drop_index(
        "uq_shelf_image_artifact_reference_lineage",
        table_name="shelf_image_artifact_references",
    )
 THEN
                        RAISE EXCEPTION 'disposition attestation requires evidence reference and SHA-256'
                            USING ERRCODE = '23514';
                    END IF;
                ELSE
                    RAISE EXCEPTION 'unsupported artifact disposition event type'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_event_validate
            BEFORE INSERT ON shelf_image_artifact_disposition_events
            FOR EACH ROW EXECUTE FUNCTION validate_shelf_image_artifact_disposition_event()
        """)
        op.execute("""
            CREATE FUNCTION prevent_shelf_image_artifact_disposition_event_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'shelf_image_artifact_disposition_events is append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_events_append_only
            BEFORE UPDATE OR DELETE ON shelf_image_artifact_disposition_events
            FOR EACH ROW EXECUTE FUNCTION prevent_shelf_image_artifact_disposition_event_mutation()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_reference_store
            BEFORE INSERT ON shelf_image_artifact_references
            WHEN NOT EXISTS (
                SELECT 1
                FROM shelf_images si
                JOIN shelves sh ON sh.id = si.shelf_id
                JOIN zones z ON z.id = sh.zone_id
                WHERE si.id = NEW.shelf_image_id
                  AND z.store_id = NEW.store_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'artifact reference store does not match shelf image lineage');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_events_no_update
            BEFORE UPDATE ON shelf_image_artifact_disposition_events
            BEGIN SELECT RAISE(ABORT, 'shelf_image_artifact_disposition_events is append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_events_no_delete
            BEFORE DELETE ON shelf_image_artifact_disposition_events
            BEGIN SELECT RAISE(ABORT, 'shelf_image_artifact_disposition_events is append-only'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_reference_store ON shelf_image_artifact_references")
        op.execute("DROP FUNCTION IF EXISTS validate_shelf_image_artifact_reference_store()")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_events_append_only ON shelf_image_artifact_disposition_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_shelf_image_artifact_disposition_event_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_reference_store")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_events_no_delete")

    op.drop_index(
        "ix_shelf_image_artifact_disposition_store_image",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_index(
        "ix_shelf_image_artifact_disposition_artifact_created",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_index(
        "ix_shelf_image_artifact_disposition_events_store_id",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_index(
        "ix_shelf_image_artifact_disposition_events_shelf_image_id",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_table("shelf_image_artifact_disposition_events")
    op.drop_index(
        "uq_shelf_image_artifact_reference_lineage",
        table_name="shelf_image_artifact_references",
    )
