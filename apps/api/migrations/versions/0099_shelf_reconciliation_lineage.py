"""Enforce SKU/shelf and reconciliation evidence lineage at the database boundary."""

from alembic import op
import sqlalchemy as sa


revision = "0099_shelf_reconciliation_lineage"
down_revision = "0098_shelf_operational_evidence_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Fail closed: historical evidence is never silently rewritten or backfilled.
    invalid_alerts = bind.execute(sa.text("""
        SELECT COUNT(*)
        FROM observation_alerts alert
        LEFT JOIN shelves shelf ON shelf.id = alert.shelf_id
        LEFT JOIN zones zone ON zone.id = shelf.zone_id
        LEFT JOIN shelf_products link
          ON link.shelf_id = alert.shelf_id AND link.product_id = alert.product_id
        WHERE zone.id IS NULL OR zone.store_id <> alert.store_id OR link.shelf_id IS NULL
    """)).scalar_one()
    invalid_reconciliations = bind.execute(sa.text("""
        SELECT COUNT(*)
        FROM inventory_reconciliations reconciliation
        LEFT JOIN shelves shelf ON shelf.id = reconciliation.shelf_id
        LEFT JOIN zones zone ON zone.id = shelf.zone_id
        LEFT JOIN shelf_products link
          ON link.shelf_id = reconciliation.shelf_id
         AND link.product_id = reconciliation.product_id
        LEFT JOIN observations observation
          ON observation.id = reconciliation.observation_id
        LEFT JOIN inventory_snapshots backroom
          ON backroom.id = reconciliation.backroom_snapshot_id
        LEFT JOIN inventory_snapshots erp
          ON erp.id = reconciliation.erp_snapshot_id
        LEFT JOIN inventory_snapshots wms
          ON wms.id = reconciliation.wms_snapshot_id
        WHERE zone.id IS NULL
           OR zone.store_id <> reconciliation.store_id
           OR link.shelf_id IS NULL
           OR (reconciliation.observation_id IS NOT NULL AND (
                observation.id IS NULL
                OR observation.shelf_id <> reconciliation.shelf_id
                OR observation.product_id IS NULL
                OR observation.product_id <> reconciliation.product_id
           ))
           OR (reconciliation.backroom_snapshot_id IS NOT NULL AND (
                backroom.id IS NULL OR backroom.store_id <> reconciliation.store_id
                OR backroom.product_id <> reconciliation.product_id
           ))
           OR (reconciliation.erp_snapshot_id IS NOT NULL AND (
                erp.id IS NULL OR erp.store_id <> reconciliation.store_id
                OR erp.product_id <> reconciliation.product_id
           ))
           OR (reconciliation.wms_snapshot_id IS NOT NULL AND (
                wms.id IS NULL OR wms.store_id <> reconciliation.store_id
                OR wms.product_id <> reconciliation.product_id
           ))
    """)).scalar_one()
    if invalid_alerts or invalid_reconciliations:
        raise RuntimeError(
            "Cannot enable shelf/reconciliation lineage guard: "
            f"{invalid_alerts} invalid alerts and "
            f"{invalid_reconciliations} invalid reconciliations; "
            "repair historical evidence explicitly before retrying"
        )

    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION enforce_shelf_alert_lineage_0099()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE actual_store_id INTEGER;
            BEGIN
                SELECT zone.store_id INTO actual_store_id
                FROM shelves shelf
                JOIN zones zone ON zone.id = shelf.zone_id
                WHERE shelf.id = NEW.shelf_id
                FOR SHARE OF shelf, zone;

                IF NOT FOUND OR actual_store_id IS DISTINCT FROM NEW.store_id THEN
                    RAISE EXCEPTION 'observation alert shelf/store lineage mismatch'
                        USING ERRCODE = '23514';
                END IF;

                PERFORM 1 FROM shelf_products
                WHERE shelf_id = NEW.shelf_id AND product_id = NEW.product_id
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'observation alert SKU is not linked to shelf'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_observation_alert_shelf_lineage_0099
            BEFORE INSERT OR UPDATE OF store_id, shelf_id, product_id
            ON observation_alerts
            FOR EACH ROW EXECUTE FUNCTION enforce_shelf_alert_lineage_0099()
        """)
        op.execute("""
            CREATE FUNCTION enforce_reconciliation_lineage_0099()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE actual_store_id INTEGER;
            DECLARE related_shelf_id INTEGER;
            DECLARE related_product_id INTEGER;
            BEGIN
                SELECT zone.store_id INTO actual_store_id
                FROM shelves shelf
                JOIN zones zone ON zone.id = shelf.zone_id
                WHERE shelf.id = NEW.shelf_id
                FOR SHARE OF shelf, zone;

                IF NOT FOUND OR actual_store_id IS DISTINCT FROM NEW.store_id THEN
                    RAISE EXCEPTION 'inventory reconciliation shelf/store lineage mismatch'
                        USING ERRCODE = '23514';
                END IF;

                PERFORM 1 FROM shelf_products
                WHERE shelf_id = NEW.shelf_id AND product_id = NEW.product_id
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'inventory reconciliation SKU is not linked to shelf'
                        USING ERRCODE = '23514';
                END IF;

                IF NEW.observation_id IS NOT NULL THEN
                    SELECT shelf_id, product_id
                    INTO related_shelf_id, related_product_id
                    FROM observations WHERE id = NEW.observation_id FOR SHARE;
                    IF NOT FOUND OR related_shelf_id IS DISTINCT FROM NEW.shelf_id
                       OR related_product_id IS DISTINCT FROM NEW.product_id THEN
                        RAISE EXCEPTION 'inventory reconciliation observation lineage mismatch'
                            USING ERRCODE = '23514';
                    END IF;
                END IF;

                IF NEW.backroom_snapshot_id IS NOT NULL THEN
                    PERFORM 1 FROM inventory_snapshots
                    WHERE id = NEW.backroom_snapshot_id
                      AND store_id = NEW.store_id AND product_id = NEW.product_id
                    FOR SHARE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'inventory reconciliation backroom snapshot lineage mismatch'
                            USING ERRCODE = '23514';
                    END IF;
                END IF;
                IF NEW.erp_snapshot_id IS NOT NULL THEN
                    PERFORM 1 FROM inventory_snapshots
                    WHERE id = NEW.erp_snapshot_id
                      AND store_id = NEW.store_id AND product_id = NEW.product_id
                    FOR SHARE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'inventory reconciliation ERP snapshot lineage mismatch'
                            USING ERRCODE = '23514';
                    END IF;
                END IF;
                IF NEW.wms_snapshot_id IS NOT NULL THEN
                    PERFORM 1 FROM inventory_snapshots
                    WHERE id = NEW.wms_snapshot_id
                      AND store_id = NEW.store_id AND product_id = NEW.product_id
                    FOR SHARE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'inventory reconciliation WMS snapshot lineage mismatch'
                            USING ERRCODE = '23514';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_reconciliation_lineage_0099
            BEFORE INSERT OR UPDATE OF store_id, shelf_id, product_id, observation_id,
                backroom_snapshot_id, erp_snapshot_id, wms_snapshot_id
            ON inventory_reconciliations
            FOR EACH ROW EXECUTE FUNCTION enforce_reconciliation_lineage_0099()
        """)
        op.execute("""
            CREATE FUNCTION prevent_referenced_shelf_product_change_0099()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF (TG_OP = 'DELETE' OR NEW.shelf_id IS DISTINCT FROM OLD.shelf_id
                    OR NEW.product_id IS DISTINCT FROM OLD.product_id)
                   AND (
                     EXISTS (SELECT 1 FROM observation_alerts
                             WHERE shelf_id = OLD.shelf_id AND product_id = OLD.product_id)
                     OR EXISTS (SELECT 1 FROM inventory_reconciliations
                                WHERE shelf_id = OLD.shelf_id AND product_id = OLD.product_id)
                   ) THEN
                    RAISE EXCEPTION 'shelf SKU association is referenced by retained evidence'
                        USING ERRCODE = '23503';
                END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_referenced_shelf_product_change_0099
            BEFORE UPDATE OR DELETE ON shelf_products
            FOR EACH ROW EXECUTE FUNCTION prevent_referenced_shelf_product_change_0099()
        """)
        op.execute("""
            CREATE FUNCTION prevent_referenced_observation_change_0099()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF (NEW.shelf_id IS DISTINCT FROM OLD.shelf_id
                    OR NEW.product_id IS DISTINCT FROM OLD.product_id)
                   AND EXISTS (
                       SELECT 1 FROM inventory_reconciliations
                       WHERE observation_id = OLD.id
                   ) THEN
                    RAISE EXCEPTION 'observation is referenced by immutable reconciliation evidence'
                        USING ERRCODE = '23503';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_referenced_observation_change_0099
            BEFORE UPDATE OF shelf_id, product_id ON observations
            FOR EACH ROW EXECUTE FUNCTION prevent_referenced_observation_change_0099()
        """)
        op.execute("""
            CREATE FUNCTION prevent_referenced_shelf_hierarchy_change_0099()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE target_store_id INTEGER;
            DECLARE has_mismatch BOOLEAN;
            BEGIN
                IF TG_TABLE_NAME = 'zones' THEN
                    target_store_id := NEW.store_id;
                    SELECT EXISTS (
                        SELECT 1 FROM shelves shelf
                        JOIN observation_alerts alert ON alert.shelf_id = shelf.id
                        WHERE shelf.zone_id = OLD.id AND alert.store_id <> target_store_id
                        UNION ALL
                        SELECT 1 FROM shelves shelf
                        JOIN inventory_reconciliations reconciliation ON reconciliation.shelf_id = shelf.id
                        WHERE shelf.zone_id = OLD.id AND reconciliation.store_id <> target_store_id
                    ) INTO has_mismatch;
                ELSE
                    SELECT store_id INTO target_store_id FROM zones WHERE id = NEW.zone_id FOR SHARE;
                    SELECT EXISTS (
                        SELECT 1 FROM observation_alerts
                        WHERE shelf_id = OLD.id AND store_id <> target_store_id
                        UNION ALL
                        SELECT 1 FROM inventory_reconciliations
                        WHERE shelf_id = OLD.id AND store_id <> target_store_id
                    ) INTO has_mismatch;
                END IF;
                IF has_mismatch THEN
                    RAISE EXCEPTION 'cannot move shelf hierarchy across stores while evidence exists'
                        USING ERRCODE = '23503';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_zone_shelf_evidence_lineage_0099
            BEFORE UPDATE OF store_id ON zones
            FOR EACH ROW WHEN (NEW.store_id IS DISTINCT FROM OLD.store_id)
            EXECUTE FUNCTION prevent_referenced_shelf_hierarchy_change_0099()
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_shelf_evidence_lineage_0099
            BEFORE UPDATE OF zone_id ON shelves
            FOR EACH ROW WHEN (NEW.zone_id IS DISTINCT FROM OLD.zone_id)
            EXECUTE FUNCTION prevent_referenced_shelf_hierarchy_change_0099()
        """)

    elif bind.dialect.name == "sqlite":
        for action in ("INSERT", "UPDATE"):
            op.execute(f"""
                CREATE TRIGGER trg_observation_alert_lineage_{action.lower()}_0099
                BEFORE {action} ON observation_alerts
                WHEN NOT EXISTS (
                    SELECT 1 FROM shelves shelf JOIN zones zone ON zone.id = shelf.zone_id
                    JOIN shelf_products link ON link.shelf_id = shelf.id
                    WHERE shelf.id = NEW.shelf_id AND zone.store_id = NEW.store_id
                      AND link.product_id = NEW.product_id
                )
                BEGIN
                    SELECT RAISE(ABORT, 'observation alert shelf/product/store lineage mismatch');
                END
            """)
            op.execute(f"""
                CREATE TRIGGER trg_inventory_reconciliation_lineage_{action.lower()}_0099
                BEFORE {action} ON inventory_reconciliations
                WHEN NOT EXISTS (
                    SELECT 1 FROM shelves shelf JOIN zones zone ON zone.id = shelf.zone_id
                    JOIN shelf_products link ON link.shelf_id = shelf.id
                    WHERE shelf.id = NEW.shelf_id AND zone.store_id = NEW.store_id
                      AND link.product_id = NEW.product_id
                )
                OR (NEW.observation_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM observations observation
                    WHERE observation.id = NEW.observation_id
                      AND observation.shelf_id = NEW.shelf_id
                      AND observation.product_id = NEW.product_id
                ))
                OR (NEW.backroom_snapshot_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM inventory_snapshots snapshot
                    WHERE snapshot.id = NEW.backroom_snapshot_id
                      AND snapshot.store_id = NEW.store_id AND snapshot.product_id = NEW.product_id
                ))
                OR (NEW.erp_snapshot_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM inventory_snapshots snapshot
                    WHERE snapshot.id = NEW.erp_snapshot_id
                      AND snapshot.store_id = NEW.store_id AND snapshot.product_id = NEW.product_id
                ))
                OR (NEW.wms_snapshot_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM inventory_snapshots snapshot
                    WHERE snapshot.id = NEW.wms_snapshot_id
                      AND snapshot.store_id = NEW.store_id AND snapshot.product_id = NEW.product_id
                ))
                BEGIN
                    SELECT RAISE(ABORT, 'inventory reconciliation evidence lineage mismatch');
                END
            """)

        op.execute("""
            CREATE TRIGGER trg_referenced_shelf_product_change_0099
            BEFORE UPDATE OF shelf_id, product_id ON shelf_products
            WHEN (NEW.shelf_id IS NOT OLD.shelf_id OR NEW.product_id IS NOT OLD.product_id)
             AND (
                EXISTS (SELECT 1 FROM observation_alerts
                        WHERE shelf_id = OLD.shelf_id AND product_id = OLD.product_id)
                OR EXISTS (SELECT 1 FROM inventory_reconciliations
                           WHERE shelf_id = OLD.shelf_id AND product_id = OLD.product_id)
             )
            BEGIN
                SELECT RAISE(ABORT, 'shelf SKU association is referenced by retained evidence');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_referenced_shelf_product_delete_0099
            BEFORE DELETE ON shelf_products
            WHEN EXISTS (SELECT 1 FROM observation_alerts
                         WHERE shelf_id = OLD.shelf_id AND product_id = OLD.product_id)
              OR EXISTS (SELECT 1 FROM inventory_reconciliations
                         WHERE shelf_id = OLD.shelf_id AND product_id = OLD.product_id)
            BEGIN
                SELECT RAISE(ABORT, 'shelf SKU association is referenced by retained evidence');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_referenced_observation_change_0099
            BEFORE UPDATE OF shelf_id, product_id ON observations
            WHEN (NEW.shelf_id IS NOT OLD.shelf_id OR NEW.product_id IS NOT OLD.product_id)
             AND EXISTS (SELECT 1 FROM inventory_reconciliations WHERE observation_id = OLD.id)
            BEGIN
                SELECT RAISE(ABORT, 'observation is referenced by immutable reconciliation evidence');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_zone_shelf_evidence_lineage_0099
            BEFORE UPDATE OF store_id ON zones
            WHEN NEW.store_id <> OLD.store_id AND (
                EXISTS (
                    SELECT 1 FROM shelves shelf
                    JOIN observation_alerts alert ON alert.shelf_id = shelf.id
                    WHERE shelf.zone_id = OLD.id AND alert.store_id <> NEW.store_id
                )
                OR EXISTS (
                    SELECT 1 FROM shelves shelf
                    JOIN inventory_reconciliations reconciliation ON reconciliation.shelf_id = shelf.id
                    WHERE shelf.zone_id = OLD.id AND reconciliation.store_id <> NEW.store_id
                )
            )
            BEGIN
                SELECT RAISE(ABORT, 'cannot move shelf hierarchy across stores while evidence exists');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_shelf_evidence_lineage_0099
            BEFORE UPDATE OF zone_id ON shelves
            WHEN NEW.zone_id <> OLD.zone_id AND (
                EXISTS (SELECT 1 FROM observation_alerts
                        WHERE shelf_id = OLD.id
                          AND store_id <> (SELECT store_id FROM zones WHERE id = NEW.zone_id))
                OR EXISTS (SELECT 1 FROM inventory_reconciliations
                           WHERE shelf_id = OLD.id
                             AND store_id <> (SELECT store_id FROM zones WHERE id = NEW.zone_id))
            )
            BEGIN
                SELECT RAISE(ABORT, 'cannot move shelf hierarchy across stores while evidence exists');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for trigger, table in (
            ("trg_shelf_shelf_evidence_lineage_0099", "shelves"),
            ("trg_zone_shelf_evidence_lineage_0099", "zones"),
            ("trg_referenced_observation_change_0099", "observations"),
            ("trg_referenced_shelf_product_change_0099", "shelf_products"),
            ("trg_inventory_reconciliation_lineage_0099", "inventory_reconciliations"),
            ("trg_observation_alert_shelf_lineage_0099", "observation_alerts"),
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        for function in (
            "prevent_referenced_shelf_hierarchy_change_0099",
            "prevent_referenced_observation_change_0099",
            "prevent_referenced_shelf_product_change_0099",
            "enforce_reconciliation_lineage_0099",
            "enforce_shelf_alert_lineage_0099",
        ):
            op.execute(f"DROP FUNCTION IF EXISTS {function}()")
    elif bind.dialect.name == "sqlite":
        for trigger in (
            "trg_shelf_shelf_evidence_lineage_0099",
            "trg_zone_shelf_evidence_lineage_0099",
            "trg_referenced_observation_change_0099",
            "trg_referenced_shelf_product_delete_0099",
            "trg_referenced_shelf_product_change_0099",
            "trg_inventory_reconciliation_lineage_insert_0099",
            "trg_inventory_reconciliation_lineage_update_0099",
            "trg_observation_alert_lineage_insert_0099",
            "trg_observation_alert_lineage_update_0099",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
