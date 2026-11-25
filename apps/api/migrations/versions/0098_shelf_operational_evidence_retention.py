"""Prevent cascading deletion of shelves/zones with retained operational evidence."""
from alembic import op


revision = "0098_shelf_operational_evidence_retention"
down_revision = "0097_replenishment_task_audit_immutability"
branch_labels = None
depends_on = None


_SHELF_EVIDENCE_TABLES = (
    "observations",
    "observation_alerts",
    "shelf_products",
    "shelf_planograms",
    "inventory_reconciliations",
    "replenishment_tasks",
    "capture_sessions",
    "shelf_images",
    "edge_device_event_inbox",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_shelf_delete_with_evidence_0098()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF EXISTS (SELECT 1 FROM observations WHERE shelf_id = OLD.id)
                   OR EXISTS (SELECT 1 FROM observation_alerts WHERE shelf_id = OLD.id)
                   OR EXISTS (SELECT 1 FROM shelf_products WHERE shelf_id = OLD.id)
                   OR EXISTS (SELECT 1 FROM shelf_planograms WHERE shelf_id = OLD.id)
                   OR EXISTS (SELECT 1 FROM inventory_reconciliations WHERE shelf_id = OLD.id)
                   OR EXISTS (SELECT 1 FROM replenishment_tasks WHERE shelf_id = OLD.id)
                   OR EXISTS (SELECT 1 FROM capture_sessions WHERE shelf_id = OLD.id)
                   OR EXISTS (SELECT 1 FROM shelf_images WHERE shelf_id = OLD.id)
                   OR EXISTS (SELECT 1 FROM edge_device_event_inbox WHERE shelf_id = OLD.id)
                THEN
                    RAISE EXCEPTION 'shelf has retained operational evidence'
                        USING ERRCODE = '23503';
                END IF;
                RETURN OLD;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_operational_evidence_retention_0098
            BEFORE DELETE ON shelves
            FOR EACH ROW EXECUTE FUNCTION prevent_shelf_delete_with_evidence_0098()
        """)
        op.execute("""
            CREATE FUNCTION prevent_zone_delete_with_evidence_0098()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM shelves AS shelf
                    WHERE shelf.zone_id = OLD.id
                      AND (
                          EXISTS (SELECT 1 FROM observations WHERE shelf_id = shelf.id)
                          OR EXISTS (SELECT 1 FROM observation_alerts WHERE shelf_id = shelf.id)
                          OR EXISTS (SELECT 1 FROM shelf_products WHERE shelf_id = shelf.id)
                          OR EXISTS (SELECT 1 FROM shelf_planograms WHERE shelf_id = shelf.id)
                          OR EXISTS (SELECT 1 FROM inventory_reconciliations WHERE shelf_id = shelf.id)
                          OR EXISTS (SELECT 1 FROM replenishment_tasks WHERE shelf_id = shelf.id)
                          OR EXISTS (SELECT 1 FROM capture_sessions WHERE shelf_id = shelf.id)
                          OR EXISTS (SELECT 1 FROM shelf_images WHERE shelf_id = shelf.id)
                          OR EXISTS (SELECT 1 FROM edge_device_event_inbox WHERE shelf_id = shelf.id)
                      )
                ) THEN
                    RAISE EXCEPTION 'zone has retained shelf evidence'
                        USING ERRCODE = '23503';
                END IF;
                RETURN OLD;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_zone_operational_evidence_retention_0098
            BEFORE DELETE ON zones
            FOR EACH ROW EXECUTE FUNCTION prevent_zone_delete_with_evidence_0098()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_shelf_operational_evidence_retention_0098
            BEFORE DELETE ON shelves
            WHEN EXISTS (SELECT 1 FROM observations WHERE shelf_id = OLD.id)
              OR EXISTS (SELECT 1 FROM observation_alerts WHERE shelf_id = OLD.id)
              OR EXISTS (SELECT 1 FROM shelf_products WHERE shelf_id = OLD.id)
              OR EXISTS (SELECT 1 FROM shelf_planograms WHERE shelf_id = OLD.id)
              OR EXISTS (SELECT 1 FROM inventory_reconciliations WHERE shelf_id = OLD.id)
              OR EXISTS (SELECT 1 FROM replenishment_tasks WHERE shelf_id = OLD.id)
              OR EXISTS (SELECT 1 FROM capture_sessions WHERE shelf_id = OLD.id)
              OR EXISTS (SELECT 1 FROM shelf_images WHERE shelf_id = OLD.id)
              OR EXISTS (SELECT 1 FROM edge_device_event_inbox WHERE shelf_id = OLD.id)
            BEGIN
                SELECT RAISE(ABORT, 'shelf has retained operational evidence');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_zone_operational_evidence_retention_0098
            BEFORE DELETE ON zones
            WHEN EXISTS (
                SELECT 1
                FROM shelves AS shelf
                WHERE shelf.zone_id = OLD.id
                  AND (
                      EXISTS (SELECT 1 FROM observations WHERE shelf_id = shelf.id)
                      OR EXISTS (SELECT 1 FROM observation_alerts WHERE shelf_id = shelf.id)
                      OR EXISTS (SELECT 1 FROM shelf_products WHERE shelf_id = shelf.id)
                      OR EXISTS (SELECT 1 FROM shelf_planograms WHERE shelf_id = shelf.id)
                      OR EXISTS (SELECT 1 FROM inventory_reconciliations WHERE shelf_id = shelf.id)
                      OR EXISTS (SELECT 1 FROM replenishment_tasks WHERE shelf_id = shelf.id)
                      OR EXISTS (SELECT 1 FROM capture_sessions WHERE shelf_id = shelf.id)
                      OR EXISTS (SELECT 1 FROM shelf_images WHERE shelf_id = shelf.id)
                      OR EXISTS (SELECT 1 FROM edge_device_event_inbox WHERE shelf_id = shelf.id)
                  )
            )
            BEGIN
                SELECT RAISE(ABORT, 'zone has retained shelf evidence');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_zone_operational_evidence_retention_0098 ON zones")
        op.execute("DROP FUNCTION IF EXISTS prevent_zone_delete_with_evidence_0098()")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_operational_evidence_retention_0098 ON shelves")
        op.execute("DROP FUNCTION IF EXISTS prevent_shelf_delete_with_evidence_0098()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_zone_operational_evidence_retention_0098")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_operational_evidence_retention_0098")
