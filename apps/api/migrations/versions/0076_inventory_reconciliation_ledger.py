"""Persist immutable inventory reconciliation evidence and human review events."""

from alembic import op
import sqlalchemy as sa

revision = "0076_inventory_reconciliation_ledger"
down_revision = "0075_task_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_reconciliations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("shelf_id", sa.Integer(), sa.ForeignKey("shelves.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("observation_id", sa.Integer(), sa.ForeignKey("observations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("backroom_snapshot_id", sa.Integer(), sa.ForeignKey("inventory_snapshots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("erp_snapshot_id", sa.Integer(), sa.ForeignKey("inventory_snapshots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("wms_snapshot_id", sa.Integer(), sa.ForeignKey("inventory_snapshots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("display_target_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("display_quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("wms_available_quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("erp_available_quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("display_delta", sa.Numeric(12, 3), nullable=True),
        sa.Column("display_vs_wms_delta", sa.Numeric(12, 3), nullable=True),
        sa.Column("display_vs_erp_delta", sa.Numeric(12, 3), nullable=True),
        sa.Column("wms_erp_delta", sa.Numeric(12, 3), nullable=True),
        sa.Column("comparison_status", sa.String(32), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(24), nullable=False, server_default="PENDING"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("review_status IN ('PENDING', 'APPROVED', 'REJECTED', 'NEEDS_INVESTIGATION')", name="ck_inventory_reconciliation_review_status"),
        sa.CheckConstraint("display_quantity IS NULL OR display_quantity >= 0", name="ck_inventory_reconciliation_display_quantity"),
        sa.CheckConstraint("wms_available_quantity IS NULL OR wms_available_quantity >= 0", name="ck_inventory_reconciliation_wms_quantity"),
        sa.CheckConstraint("erp_available_quantity IS NULL OR erp_available_quantity >= 0", name="ck_inventory_reconciliation_erp_quantity"),
    )
    op.create_index("ix_inventory_reconciliations_store_id", "inventory_reconciliations", ["store_id"])
    op.create_index("ix_inventory_reconciliations_shelf_id", "inventory_reconciliations", ["shelf_id"])
    op.create_index("ix_inventory_reconciliations_product_id", "inventory_reconciliations", ["product_id"])
    op.create_index("ix_inventory_reconciliations_review_status", "inventory_reconciliations", ["review_status"])
    op.create_index("ix_inventory_reconciliation_store_status_created", "inventory_reconciliations", ["store_id", "review_status", "created_at"])
    op.create_index("ix_inventory_reconciliation_product_created", "inventory_reconciliations", ["store_id", "product_id", "created_at"])
    op.create_table(
        "inventory_reconciliation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reconciliation_id", sa.Integer(), sa.ForeignKey("inventory_reconciliations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_type IN ('CREATED', 'APPROVED', 'REJECTED', 'NEEDS_INVESTIGATION')", name="ck_inventory_reconciliation_event_type"),
    )
    op.create_index("ix_inventory_reconciliation_events_reconciliation_id", "inventory_reconciliation_events", ["reconciliation_id"])
    op.create_index("ix_inventory_reconciliation_events_actor_user_id", "inventory_reconciliation_events", ["actor_user_id"])
    op.create_index("ix_inventory_reconciliation_events_created_at", "inventory_reconciliation_events", ["created_at"])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_inventory_reconciliation_event_mutation_0076()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'inventory_reconciliation_events is append-only' USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_reconciliation_events_append_only
            BEFORE UPDATE OR DELETE ON inventory_reconciliation_events
            FOR EACH ROW EXECUTE FUNCTION prevent_inventory_reconciliation_event_mutation_0076()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_inventory_reconciliation_evidence_mutation_0076()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF ROW(
                    NEW.store_id, NEW.shelf_id, NEW.product_id, NEW.observation_id,
                    NEW.backroom_snapshot_id, NEW.erp_snapshot_id, NEW.wms_snapshot_id,
                    NEW.display_target_quantity, NEW.display_quantity, NEW.wms_available_quantity,
                    NEW.erp_available_quantity, NEW.display_delta, NEW.display_vs_wms_delta,
                    NEW.display_vs_erp_delta, NEW.wms_erp_delta, NEW.comparison_status,
                    NEW.evidence, NEW.created_by_user_id, NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.store_id, OLD.shelf_id, OLD.product_id, OLD.observation_id,
                    OLD.backroom_snapshot_id, OLD.erp_snapshot_id, OLD.wms_snapshot_id,
                    OLD.display_target_quantity, OLD.display_quantity, OLD.wms_available_quantity,
                    OLD.erp_available_quantity, OLD.display_delta, OLD.display_vs_wms_delta,
                    OLD.display_vs_erp_delta, OLD.wms_erp_delta, OLD.comparison_status,
                    OLD.evidence, OLD.created_by_user_id, OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'inventory reconciliation evidence is immutable' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_reconciliation_evidence_immutable
            BEFORE UPDATE ON inventory_reconciliations
            FOR EACH ROW EXECUTE FUNCTION prevent_inventory_reconciliation_evidence_mutation_0076()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_inventory_reconciliation_events_no_update
            BEFORE UPDATE ON inventory_reconciliation_events
            BEGIN SELECT RAISE(ABORT, 'inventory_reconciliation_events is append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_reconciliation_events_no_delete
            BEFORE DELETE ON inventory_reconciliation_events
            BEGIN SELECT RAISE(ABORT, 'inventory_reconciliation_events is append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_reconciliation_evidence_immutable
            BEFORE UPDATE ON inventory_reconciliations
            WHEN OLD.store_id IS NOT NEW.store_id OR OLD.shelf_id IS NOT NEW.shelf_id
              OR OLD.product_id IS NOT NEW.product_id OR OLD.observation_id IS NOT NEW.observation_id
              OR OLD.backroom_snapshot_id IS NOT NEW.backroom_snapshot_id
              OR OLD.erp_snapshot_id IS NOT NEW.erp_snapshot_id OR OLD.wms_snapshot_id IS NOT NEW.wms_snapshot_id
              OR OLD.display_target_quantity IS NOT NEW.display_target_quantity
              OR OLD.display_quantity IS NOT NEW.display_quantity
              OR OLD.wms_available_quantity IS NOT NEW.wms_available_quantity
              OR OLD.erp_available_quantity IS NOT NEW.erp_available_quantity
              OR OLD.display_delta IS NOT NEW.display_delta
              OR OLD.display_vs_wms_delta IS NOT NEW.display_vs_wms_delta
              OR OLD.display_vs_erp_delta IS NOT NEW.display_vs_erp_delta
              OR OLD.wms_erp_delta IS NOT NEW.wms_erp_delta
              OR OLD.comparison_status IS NOT NEW.comparison_status
              OR OLD.evidence IS NOT NEW.evidence
              OR OLD.created_by_user_id IS NOT NEW.created_by_user_id
              OR OLD.created_at IS NOT NEW.created_at
            BEGIN SELECT RAISE(ABORT, 'inventory reconciliation evidence is immutable'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_reconciliation_evidence_immutable ON inventory_reconciliations")
        op.execute("DROP FUNCTION IF EXISTS prevent_inventory_reconciliation_evidence_mutation_0076()")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_reconciliation_events_append_only ON inventory_reconciliation_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_inventory_reconciliation_event_mutation_0076()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_reconciliation_evidence_immutable")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_reconciliation_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_reconciliation_events_no_delete")
    op.drop_table("inventory_reconciliation_events")
    op.drop_index("ix_inventory_reconciliation_product_created", table_name="inventory_reconciliations")
    op.drop_index("ix_inventory_reconciliation_store_status_created", table_name="inventory_reconciliations")
    op.drop_index("ix_inventory_reconciliations_review_status", table_name="inventory_reconciliations")
    op.drop_index("ix_inventory_reconciliations_product_id", table_name="inventory_reconciliations")
    op.drop_index("ix_inventory_reconciliations_shelf_id", table_name="inventory_reconciliations")
    op.drop_index("ix_inventory_reconciliations_store_id", table_name="inventory_reconciliations")
    op.drop_table("inventory_reconciliations")
