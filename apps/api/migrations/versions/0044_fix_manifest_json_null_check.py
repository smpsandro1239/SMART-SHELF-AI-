"""Fix JSON null validation in PostgreSQL artifact inventory manifests.

PostgreSQL's json type has no equality operator. Use ->> to distinguish an
absent/JSON-null SHA-256 from a supplied textual digest.
"""

from alembic import op


revision = "0044_fix_manifest_json_null_check"
down_revision = "0043_artifact_inventory_manifest_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("""
        CREATE OR REPLACE FUNCTION validate_artifact_inventory_manifest_integrity()
        RETURNS trigger LANGUAGE plpgsql AS $function$
        DECLARE
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
                       item ->> 'sha256' IS NOT NULL
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


def downgrade() -> None:
    # The previous function is intentionally not restored: migration 0043's
    # implementation raises a PostgreSQL operator error for JSON SHA-256 nulls.
    pass
