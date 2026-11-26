"""Add immutable Edge task assignment history and database-owned task revisions."""

from alembic import op
import sqlalchemy as sa


revision = "0102_edge_task_assignments"
down_revision = "0101_inventory_sync_job_store_immutable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_replenishment_task_id_store",
        "replenishment_tasks",
        ["id", "store_id"],
        unique=True,
    )
    op.create_index(
        "uq_edge_device_id_store",
        "edge_devices",
        ["device_id", "store_id"],
        unique=True,
    )

    op.add_column(
        "replenishment_tasks",
        sa.Column("task_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        "ck_replenishment_task_version_positive",
        "replenishment_tasks",
        "task_version > 0",
    )

    op.create_table(
        "edge_device_task_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("device_id", sa.String(length=120), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("task_version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["device_id", "store_id"],
            ["edge_devices.device_id", "edge_devices.store_id"],
            ondelete="RESTRICT",
            name="fk_edge_task_assignment_device_store",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "store_id"],
            ["replenishment_tasks.id", "replenishment_tasks.store_id"],
            ondelete="RESTRICT",
            name="fk_edge_task_assignment_task_store",
        ),
        sa.CheckConstraint("task_version > 0", name="ck_edge_task_assignment_task_version"),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_edge_task_assignment_validity",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL AND length(trim(revocation_reason)) >= 3)",
            name="ck_edge_task_assignment_revocation",
        ),
    )
    op.create_index(
        "uq_edge_task_assignment_active_device_task",
        "edge_device_task_assignments",
        ["device_id", "task_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_edge_task_assignment_store_task",
        "edge_device_task_assignments",
        ["store_id", "task_id", "valid_from"],
    )
    op.create_index(
        "ix_edge_task_assignment_device_validity",
        "edge_device_task_assignments",
        ["device_id", "valid_from", "valid_until"],
    )

    op.create_table(
        "edge_device_task_assignment_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "assignment_id",
            sa.Integer(),
            sa.ForeignKey("edge_device_task_assignments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=12), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("event_type IN ('CREATED', 'REVOKED')", name="ck_edge_task_assignment_event_type"),
        sa.CheckConstraint("length(trim(reason)) >= 3", name="ck_edge_task_assignment_event_reason"),
    )
    op.create_index(
        "ix_edge_task_assignment_events_assignment_created",
        "edge_device_task_assignment_events",
        ["assignment_id", "created_at"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION bump_replenishment_task_version_0102()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                NEW.task_version := OLD.task_version + 1;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_replenishment_task_version_0102
            BEFORE UPDATE ON replenishment_tasks
            FOR EACH ROW EXECUTE FUNCTION bump_replenishment_task_version_0102()
        """)
        op.execute("""
            CREATE FUNCTION guard_edge_task_assignment_mutation_0102()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'assignment history is append-only'
                        USING ERRCODE = '23514';
                END IF;
                IF OLD.revoked_at IS NOT NULL
                   OR (NEW.id, NEW.store_id, NEW.device_id, NEW.task_id, NEW.task_version,
                       NEW.valid_from, NEW.valid_until, NEW.created_by_user_id, NEW.created_at)
                      IS DISTINCT FROM
                      (OLD.id, OLD.store_id, OLD.device_id, OLD.task_id, OLD.task_version,
                       OLD.valid_from, OLD.valid_until, OLD.created_by_user_id, OLD.created_at)
                   OR NEW.revoked_at IS NULL
                   OR NEW.revoked_by_user_id IS NULL
                   OR length(trim(NEW.revocation_reason)) < 3 THEN
                    RAISE EXCEPTION 'assignment identity is immutable; only one valid revocation is allowed'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_edge_task_assignment_update_guard_0102
            BEFORE UPDATE ON edge_device_task_assignments
            FOR EACH ROW EXECUTE FUNCTION guard_edge_task_assignment_mutation_0102()
        """)
        op.execute("""
            CREATE TRIGGER trg_edge_task_assignment_delete_guard_0102
            BEFORE DELETE ON edge_device_task_assignments
            FOR EACH ROW EXECUTE FUNCTION guard_edge_task_assignment_mutation_0102()
        """)
        op.execute("""
            CREATE FUNCTION guard_edge_task_assignment_event_immutability_0102()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'assignment events are append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_edge_task_assignment_event_immutable_0102
            BEFORE UPDATE OR DELETE ON edge_device_task_assignment_events
            FOR EACH ROW EXECUTE FUNCTION guard_edge_task_assignment_event_immutability_0102()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_replenishment_task_version_0102
            AFTER UPDATE ON replenishment_tasks
            WHEN NEW.task_version <> OLD.task_version + 1
            BEGIN
                UPDATE replenishment_tasks
                SET task_version = OLD.task_version + 1
                WHERE id = NEW.id;
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_edge_task_assignment_update_guard_0102
            BEFORE UPDATE ON edge_device_task_assignments
            WHEN OLD.revoked_at IS NOT NULL
              OR NEW.id IS NOT OLD.id
              OR NEW.store_id IS NOT OLD.store_id
              OR NEW.device_id IS NOT OLD.device_id
              OR NEW.task_id IS NOT OLD.task_id
              OR NEW.task_version IS NOT OLD.task_version
              OR NEW.valid_from IS NOT OLD.valid_from
              OR NEW.valid_until IS NOT OLD.valid_until
              OR NEW.created_by_user_id IS NOT OLD.created_by_user_id
              OR NEW.created_at IS NOT OLD.created_at
              OR NEW.revoked_at IS NULL
              OR NEW.revoked_by_user_id IS NULL
              OR length(trim(NEW.revocation_reason)) < 3
            BEGIN
                SELECT RAISE(ABORT, 'assignment identity is immutable; only one valid revocation is allowed');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_edge_task_assignment_delete_guard_0102
            BEFORE DELETE ON edge_device_task_assignments
            BEGIN
                SELECT RAISE(ABORT, 'assignment history is append-only');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_edge_task_assignment_event_update_guard_0102
            BEFORE UPDATE ON edge_device_task_assignment_events
            BEGIN
                SELECT RAISE(ABORT, 'assignment events are append-only');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_edge_task_assignment_event_delete_guard_0102
            BEFORE DELETE ON edge_device_task_assignment_events
            BEGIN
                SELECT RAISE(ABORT, 'assignment events are append-only');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_edge_task_assignment_event_immutable_0102 ON edge_device_task_assignment_events")
        op.execute("DROP FUNCTION IF EXISTS guard_edge_task_assignment_event_immutability_0102()")
        op.execute("DROP TRIGGER IF EXISTS trg_edge_task_assignment_delete_guard_0102 ON edge_device_task_assignments")
        op.execute("DROP TRIGGER IF EXISTS trg_edge_task_assignment_update_guard_0102 ON edge_device_task_assignments")
        op.execute("DROP FUNCTION IF EXISTS guard_edge_task_assignment_mutation_0102()")
        op.execute("DROP TRIGGER IF EXISTS trg_replenishment_task_version_0102 ON replenishment_tasks")
        op.execute("DROP FUNCTION IF EXISTS bump_replenishment_task_version_0102()")
    elif bind.dialect.name == "sqlite":
        for name in (
            "trg_edge_task_assignment_event_delete_guard_0102",
            "trg_edge_task_assignment_event_update_guard_0102",
            "trg_edge_task_assignment_delete_guard_0102",
            "trg_edge_task_assignment_update_guard_0102",
            "trg_replenishment_task_version_0102",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")

    op.drop_index("ix_edge_task_assignment_events_assignment_created", table_name="edge_device_task_assignment_events")
    op.drop_table("edge_device_task_assignment_events")
    op.drop_index("ix_edge_task_assignment_device_validity", table_name="edge_device_task_assignments")
    op.drop_index("ix_edge_task_assignment_store_task", table_name="edge_device_task_assignments")
    op.drop_index("uq_edge_task_assignment_active_device_task", table_name="edge_device_task_assignments")
    op.drop_table("edge_device_task_assignments")
    op.drop_constraint("ck_replenishment_task_version_positive", "replenishment_tasks", type_="check")
    op.drop_column("replenishment_tasks", "task_version")
    op.drop_index("uq_edge_device_id_store", table_name="edge_devices")
    op.drop_index("uq_replenishment_task_id_store", table_name="replenishment_tasks")
