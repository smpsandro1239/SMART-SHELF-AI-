"""Allow the provider run ID to be finalized with the terminal sync transition."""
from alembic import op

revision = "0079_inventory_sync_run_identity"
down_revision = "0078_inventory_external_product_mapping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_source_sync_lifecycle_0077 ON inventory_source_syncs")
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_source_sync_lifecycle_0077()")
        op.execute("""
        CREATE FUNCTION guard_inventory_source_sync_lifecycle_0079() RETURNS trigger AS $$
        BEGIN
            IF OLD.status <> 'STARTED' OR NEW.status NOT IN ('SUCCESS', 'PARTIAL', 'FAILED')
               OR NEW.store_id IS DISTINCT FROM OLD.store_id OR NEW.source IS DISTINCT FROM OLD.source
               OR NEW.provider IS DISTINCT FROM OLD.provider
               OR (NEW.external_run_id IS DISTINCT FROM OLD.external_run_id AND OLD.external_run_id IS NOT NULL)
               OR NEW.started_at IS DISTINCT FROM OLD.started_at OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.finished_at IS NULL THEN
                RAISE EXCEPTION 'inventory source sync lifecycle permits one STARTED-to-terminal transition only';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """)
        op.execute("CREATE TRIGGER trg_inventory_source_sync_lifecycle_0079 BEFORE UPDATE ON inventory_source_syncs FOR EACH ROW EXECUTE FUNCTION guard_inventory_source_sync_lifecycle_0079()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_source_sync_lifecycle_0077")
        op.execute("""
        CREATE TRIGGER trg_inventory_source_sync_lifecycle_0079 BEFORE UPDATE ON inventory_source_syncs
        WHEN OLD.status <> 'STARTED' OR NEW.status NOT IN ('SUCCESS', 'PARTIAL', 'FAILED')
          OR NEW.store_id IS NOT OLD.store_id OR NEW.source IS NOT OLD.source
          OR NEW.provider IS NOT OLD.provider
          OR (NEW.external_run_id IS NOT OLD.external_run_id AND OLD.external_run_id IS NOT NULL)
          OR NEW.started_at IS NOT OLD.started_at OR NEW.created_by_user_id IS NOT OLD.created_by_user_id
          OR NEW.created_at IS NOT OLD.created_at OR NEW.finished_at IS NULL
        BEGIN SELECT RAISE(ABORT, 'inventory source sync lifecycle permits one STARTED-to-terminal transition only'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_source_sync_lifecycle_0079 ON inventory_source_syncs")
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_source_sync_lifecycle_0079()")
        op.execute("""
        CREATE FUNCTION guard_inventory_source_sync_lifecycle_0077() RETURNS trigger AS $$
        BEGIN
            IF OLD.status <> 'STARTED' OR NEW.status NOT IN ('SUCCESS', 'PARTIAL', 'FAILED')
               OR NEW.store_id IS DISTINCT FROM OLD.store_id OR NEW.source IS DISTINCT FROM OLD.source
               OR NEW.provider IS DISTINCT FROM OLD.provider OR NEW.external_run_id IS DISTINCT FROM OLD.external_run_id
               OR NEW.started_at IS DISTINCT FROM OLD.started_at OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.finished_at IS NULL THEN
                RAISE EXCEPTION 'inventory source sync lifecycle permits one STARTED-to-terminal transition only';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """)
        op.execute("CREATE TRIGGER trg_inventory_source_sync_lifecycle_0077 BEFORE UPDATE ON inventory_source_syncs FOR EACH ROW EXECUTE FUNCTION guard_inventory_source_sync_lifecycle_0077()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_source_sync_lifecycle_0079")
        op.execute("""
        CREATE TRIGGER trg_inventory_source_sync_lifecycle_0077 BEFORE UPDATE ON inventory_source_syncs
        WHEN OLD.status <> 'STARTED' OR NEW.status NOT IN ('SUCCESS', 'PARTIAL', 'FAILED')
          OR NEW.store_id IS NOT OLD.store_id OR NEW.source IS NOT OLD.source
          OR NEW.provider IS NOT OLD.provider OR NEW.external_run_id IS NOT OLD.external_run_id
          OR NEW.started_at IS NOT OLD.started_at OR NEW.created_by_user_id IS NOT OLD.created_by_user_id
          OR NEW.created_at IS NOT OLD.created_at OR NEW.finished_at IS NULL
        BEGIN SELECT RAISE(ABORT, 'inventory source sync lifecycle permits one STARTED-to-terminal transition only'); END
        """)
