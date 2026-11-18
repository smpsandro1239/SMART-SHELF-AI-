"""Protect physical pallet lifecycle events from UPDATE and DELETE."""

from alembic import op


revision = "0055_pallet_rotation_events_append_only"
down_revision = "0054_unique_active_product_packaging_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_pallet_rotation_event_mutation_0055()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            BEGIN
                RAISE EXCEPTION 'pallet_rotation_events is append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            DROP TRIGGER IF EXISTS trg_pallet_rotation_events_append_only
            ON pallet_rotation_events
        """)
        op.execute("""
            CREATE TRIGGER trg_pallet_rotation_events_append_only
            BEFORE UPDATE OR DELETE ON pallet_rotation_events
            FOR EACH ROW
            EXECUTE FUNCTION prevent_pallet_rotation_event_mutation_0055()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_pallet_rotation_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_pallet_rotation_events_no_delete")
        op.execute("""
            CREATE TRIGGER trg_pallet_rotation_events_no_update
            BEFORE UPDATE ON pallet_rotation_events
            BEGIN
                SELECT RAISE(ABORT, 'pallet_rotation_events is append-only');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_pallet_rotation_events_no_delete
            BEFORE DELETE ON pallet_rotation_events
            BEGIN
                SELECT RAISE(ABORT, 'pallet_rotation_events is append-only');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_pallet_rotation_events_append_only "
            "ON pallet_rotation_events"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS "
            "prevent_pallet_rotation_event_mutation_0055()"
        )
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_pallet_rotation_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_pallet_rotation_events_no_delete")
