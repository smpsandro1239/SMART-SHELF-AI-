"""Protect external mapping identity and prohibit deletion after audit begins."""
from alembic import op

revision = "0081_inventory_external_mapping_identity_guard"
down_revision = "0080_inventory_external_mapping_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
        CREATE FUNCTION guard_inventory_external_mapping_identity_0081() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'inventory external product mappings cannot be deleted; deactivate them instead';
            END IF;
            IF NEW.store_id IS DISTINCT FROM OLD.store_id
               OR NEW.source IS DISTINCT FROM OLD.source
               OR NEW.external_product_id IS DISTINCT FROM OLD.external_product_id
               OR NEW.external_sku IS DISTINCT FROM OLD.external_sku THEN
                RAISE EXCEPTION 'inventory external product mapping identity is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """)
        op.execute("CREATE TRIGGER trg_inventory_external_mapping_identity_0081 BEFORE UPDATE OR DELETE ON inventory_external_product_mappings FOR EACH ROW EXECUTE FUNCTION guard_inventory_external_mapping_identity_0081()")
    elif bind.dialect.name == "sqlite":
        op.execute("""
        CREATE TRIGGER trg_inventory_external_mapping_identity_update_0081
        BEFORE UPDATE ON inventory_external_product_mappings
        WHEN NEW.store_id IS NOT OLD.store_id
          OR NEW.source IS NOT OLD.source
          OR NEW.external_product_id IS NOT OLD.external_product_id
          OR NEW.external_sku IS NOT OLD.external_sku
        BEGIN SELECT RAISE(ABORT, 'inventory external product mapping identity is immutable'); END
        """)
        op.execute("""
        CREATE TRIGGER trg_inventory_external_mapping_identity_delete_0081
        BEFORE DELETE ON inventory_external_product_mappings
        BEGIN SELECT RAISE(ABORT, 'inventory external product mappings cannot be deleted; deactivate them instead'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_external_mapping_identity_0081 ON inventory_external_product_mappings")
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_external_mapping_identity_0081()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_external_mapping_identity_update_0081")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_external_mapping_identity_delete_0081")
