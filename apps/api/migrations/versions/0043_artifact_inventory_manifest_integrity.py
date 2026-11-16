"""Validate artifact inventory manifest structure and reference coverage in the database."""

from alembic import op


revision = "0043_artifact_inventory_manifest_integrity"
down_revision = "0042_snapshot_after_disposition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION validate_artifact_inventory_manifest_integrity()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE
                manifest_entry JSON;
                entry_count INTEGER;
                present_entries INTEGER;
                absent_entries INTEGER;
                reference_count INTEGER;
            BEGIN
                IF json_typeof(NEW.inventory_manifest) IS DISTINCT FROM 'array' THEN
                    RAISE EXCEPTION 'artifact inventory manifest must be a JSON array'
                        USING ERRCODE = '23514';
                END IF;

                SELECT COUNT(*) INTO entry_count
                FROM json_array_elements(NEW.inventory_manifest);

                SELECT COUNT(*) INTO present_entries
                FROM json_array_elements(NEW.inventory_manifest) AS item
                WHERE item ->> 'state' = 'PRESENT';

                SELECT COUNT(*) INTO absent_entries
                FROM json_array_elements(NEW.inventory_manifest) AS item
                WHERE item ->> 'state' = 'ABSENT';

                IF NEW.inventory_complete IS NOT TRUE
                   OR NEW.artifact_count <> entry_count
                   OR NEW.present_count <> present_entries
                   OR NEW.absent_count <> absent_entries
                   OR entry_count <> present_entries + absent_entries THEN
                    RAISE EXCEPTION 'artifact inventory manifest counters or completeness are inconsistent'
                        USING ERRCODE = '23514';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM json_array_elements(NEW.inventory_manifest) AS item
                    WHERE json_typeof(item) <> 'object'
                       OR COALESCE(item ->> 'artifact_type', '') NOT IN
                          ('DATASET_COPY', 'DATASET_RELEASE', 'CROP', 'REPORT', 'BACKUP', 'CACHE', 'OBJECT_REPLICA', 'OTHER')
                       OR COALESCE(btrim(item ->> 'external_reference'), '') = ''
                       OR COALESCE(item ->> 'state', '') NOT IN ('PRESENT', 'ABSENT')
                       OR (
                           item -> 'sha256' IS NOT NULL
                           AND item -> 'sha256' <> 'null'::json
                           AND (item ->> 'sha256') !~ '^[0-9a-f]{64}$'
                       )
                ) THEN
                    RAISE EXCEPTION 'artifact inventory manifest contains an invalid entry'
                        USING ERRCODE = '23514';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM json_array_elements(NEW.inventory_manifest) AS item
                    GROUP BY item ->> 'artifact_type', item ->> 'external_reference'
                    HAVING COUNT(*) > 1
                ) THEN
                    RAISE EXCEPTION 'artifact inventory manifest contains duplicate identities'
                        USING ERRCODE = '23514';
                END IF;

                SELECT COUNT(*) INTO reference_count
                FROM shelf_image_artifact_references reference
                WHERE reference.shelf_image_id = NEW.shelf_image_id
                  AND reference.store_id = NEW.store_id
                  AND reference.external_system = NEW.external_system;

                IF reference_count <> entry_count OR EXISTS (
                    SELECT 1
                    FROM shelf_image_artifact_references reference
                    WHERE reference.shelf_image_id = NEW.shelf_image_id
                      AND reference.store_id = NEW.store_id
                      AND reference.external_system = NEW.external_system
                      AND NOT EXISTS (
                          SELECT 1
                          FROM json_array_elements(NEW.inventory_manifest) AS item
                          WHERE item ->> 'artifact_type' = reference.artifact_type
                            AND item ->> 'external_reference' = reference.external_reference
                            AND (item ->> 'sha256') IS NOT DISTINCT FROM reference.sha256
                      )
                ) OR EXISTS (
                    SELECT 1
                    FROM json_array_elements(NEW.inventory_manifest) AS item
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM shelf_image_artifact_references reference
                        WHERE reference.shelf_image_id = NEW.shelf_image_id
                          AND reference.store_id = NEW.store_id
                          AND reference.external_system = NEW.external_system
                          AND reference.artifact_type = item ->> 'artifact_type'
                          AND reference.external_reference = item ->> 'external_reference'
                          AND reference.sha256 IS NOT DISTINCT FROM (item ->> 'sha256')
                    )
                ) THEN
                    RAISE EXCEPTION 'artifact inventory manifest does not exactly cover declared references'
                        USING ERRCODE = '23514';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM json_array_elements(NEW.inventory_manifest) AS item
                    WHERE item ->> 'state' = 'ABSENT'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM shelf_image_artifact_references reference
                          JOIN shelf_image_artifact_disposition_events event
                            ON event.artifact_reference_id = reference.id
                          WHERE reference.shelf_image_id = NEW.shelf_image_id
                            AND reference.store_id = NEW.store_id
                            AND reference.external_system = NEW.external_system
                            AND reference.artifact_type = item ->> 'artifact_type'
                            AND reference.external_reference = item ->> 'external_reference'
                            AND reference.sha256 IS NOT DISTINCT FROM (item ->> 'sha256')
                            AND event.event_type = 'DISPOSAL_ATTESTED'
                            AND event.sequence_number = (
                                SELECT MAX(latest.sequence_number)
                                FROM shelf_image_artifact_disposition_events latest
                                WHERE latest.artifact_reference_id = reference.id
                            )
                      )
                ) THEN
                    RAISE EXCEPTION 'absent artifact requires a final disposal attestation'
                        USING ERRCODE = '23514';
                END IF;

                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_zz_artifact_inventory_manifest_integrity
            BEFORE INSERT ON shelf_image_artifact_inventory_snapshots
            FOR EACH ROW
            EXECUTE FUNCTION validate_artifact_inventory_manifest_integrity()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_zz_artifact_inventory_manifest_integrity
            BEFORE INSERT ON shelf_image_artifact_inventory_snapshots
            BEGIN
                SELECT CASE WHEN json_valid(NEW.inventory_manifest) = 0
                    OR json_type(NEW.inventory_manifest) <> 'array'
                    THEN RAISE(ABORT, 'artifact inventory manifest must be a JSON array') END;

                SELECT CASE WHEN NEW.inventory_complete <> 1
                    OR NEW.artifact_count <> (SELECT COUNT(*) FROM json_each(NEW.inventory_manifest))
                    OR NEW.present_count <> (
                        SELECT COUNT(*) FROM json_each(NEW.inventory_manifest)
                        WHERE json_extract(value, '$.state') = 'PRESENT'
                    )
                    OR NEW.absent_count <> (
                        SELECT COUNT(*) FROM json_each(NEW.inventory_manifest)
                        WHERE json_extract(value, '$.state') = 'ABSENT'
                    )
                    THEN RAISE(ABORT, 'artifact inventory manifest counters or completeness are inconsistent') END;

                SELECT CASE WHEN EXISTS (
                    SELECT 1 FROM json_each(NEW.inventory_manifest)
                    WHERE type <> 'object'
                       OR COALESCE(json_extract(value, '$.artifact_type'), '') NOT IN
                          ('DATASET_COPY', 'DATASET_RELEASE', 'CROP', 'REPORT', 'BACKUP', 'CACHE', 'OBJECT_REPLICA', 'OTHER')
                       OR trim(COALESCE(json_extract(value, '$.external_reference'), '')) = ''
                       OR COALESCE(json_extract(value, '$.state'), '') NOT IN ('PRESENT', 'ABSENT')
                       OR (
                           json_type(value, '$.sha256') IS NOT NULL
                           AND json_type(value, '$.sha256') <> 'null'
                           AND (
                               length(json_extract(value, '$.sha256')) <> 64
                               OR json_extract(value, '$.sha256') GLOB '*[^0-9a-f]*'
                           )
                       )
                ) THEN RAISE(ABORT, 'artifact inventory manifest contains an invalid entry') END;

                SELECT CASE WHEN EXISTS (
                    SELECT 1 FROM json_each(NEW.inventory_manifest)
                    GROUP BY json_extract(value, '$.artifact_type'),
                             json_extract(value, '$.external_reference')
                    HAVING COUNT(*) > 1
                ) THEN RAISE(ABORT, 'artifact inventory manifest contains duplicate identities') END;

                SELECT CASE WHEN NEW.artifact_count <> (
                    SELECT COUNT(*) FROM shelf_image_artifact_references
                    WHERE shelf_image_id = NEW.shelf_image_id
                      AND store_id = NEW.store_id
                      AND external_system = NEW.external_system
                ) THEN RAISE(ABORT, 'artifact inventory manifest does not exactly cover declared references') END;

                SELECT CASE WHEN EXISTS (
                    SELECT 1
                    FROM shelf_image_artifact_references reference
                    WHERE reference.shelf_image_id = NEW.shelf_image_id
                      AND reference.store_id = NEW.store_id
                      AND reference.external_system = NEW.external_system
                      AND NOT EXISTS (
                          SELECT 1 FROM json_each(NEW.inventory_manifest) item
                          WHERE json_extract(item.value, '$.artifact_type') = reference.artifact_type
                            AND json_extract(item.value, '$.external_reference') = reference.external_reference
                            AND json_extract(item.value, '$.sha256') IS reference.sha256
                      )
                ) OR EXISTS (
                    SELECT 1 FROM json_each(NEW.inventory_manifest) item
                    WHERE NOT EXISTS (
                        SELECT 1 FROM shelf_image_artifact_references reference
                        WHERE reference.shelf_image_id = NEW.shelf_image_id
                          AND reference.store_id = NEW.store_id
                          AND reference.external_system = NEW.external_system
                          AND reference.artifact_type = json_extract(item.value, '$.artifact_type')
                          AND reference.external_reference = json_extract(item.value, '$.external_reference')
                          AND reference.sha256 IS json_extract(item.value, '$.sha256')
                    )
                ) THEN RAISE(ABORT, 'artifact inventory manifest does not exactly cover declared references') END;

                SELECT CASE WHEN EXISTS (
                    SELECT 1
                    FROM json_each(NEW.inventory_manifest) item
                    WHERE json_extract(item.value, '$.state') = 'ABSENT'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM shelf_image_artifact_references reference
                          JOIN shelf_image_artifact_disposition_events event
                            ON event.artifact_reference_id = reference.id
                          WHERE reference.shelf_image_id = NEW.shelf_image_id
                            AND reference.store_id = NEW.store_id
                            AND reference.external_system = NEW.external_system
                            AND reference.artifact_type = json_extract(item.value, '$.artifact_type')
                            AND reference.external_reference = json_extract(item.value, '$.external_reference')
                            AND reference.sha256 IS json_extract(item.value, '$.sha256')
                            AND event.event_type = 'DISPOSAL_ATTESTED'
                            AND event.sequence_number = (
                                SELECT MAX(latest.sequence_number)
                                FROM shelf_image_artifact_disposition_events latest
                                WHERE latest.artifact_reference_id = reference.id
                            )
                      )
                ) THEN RAISE(ABORT, 'absent artifact requires a final disposal attestation') END;
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_zz_artifact_inventory_manifest_integrity "
            "ON shelf_image_artifact_inventory_snapshots"
        )
        op.execute("DROP FUNCTION IF EXISTS validate_artifact_inventory_manifest_integrity()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_zz_artifact_inventory_manifest_integrity")
