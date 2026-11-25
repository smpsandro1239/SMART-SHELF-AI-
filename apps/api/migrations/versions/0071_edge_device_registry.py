"""Introduce tenant-bound physical edge device identities and durable event inbox."""

from alembic import op
import sqlalchemy as sa


revision = "0071_edge_device_registry"
down_revision = "0070_vision_model_trust_runtime_readonly"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "edge_devices",
        sa.Column("device_id", sa.String(length=120), primary_key=True, nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("device_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="ck_edge_device_status"),
        sa.CheckConstraint("device_type IN ('fixed_camera', 'robot', 'mobile', 'gateway')", name="ck_edge_device_type"),
    )
    op.create_index("ix_edge_devices_store_status", "edge_devices", ["store_id", "status"])

    op.create_table(
        "edge_device_credentials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("credential_id", sa.String(length=32), nullable=False),
        sa.Column("device_id", sa.String(length=120), sa.ForeignKey("edge_devices.device_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("secret_sha256", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_credential_id", sa.String(length=32), nullable=True),
        sa.UniqueConstraint("credential_id", name="uq_edge_device_credential_public_id"),
        sa.CheckConstraint("length(secret_sha256) = 64", name="ck_edge_device_credential_digest"),
        sa.CheckConstraint("expires_at > created_at", name="ck_edge_device_credential_expiry"),
    )
    op.create_index("ix_edge_device_credentials_device_id", "edge_device_credentials", ["device_id"])
    op.create_index("ix_edge_device_credentials_device_expiry", "edge_device_credentials", ["device_id", "expires_at"])

    op.create_table(
        "edge_device_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.String(length=120), sa.ForeignKey("edge_devices.device_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("credential_id", sa.String(length=32), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('DEVICE_REGISTERED', 'DEVICE_DISABLED', 'CREDENTIAL_ISSUED', 'CREDENTIAL_ROTATED', 'CREDENTIAL_REVOKED')",
            name="ck_edge_device_audit_event_type",
        ),
    )
    op.create_index("ix_edge_device_audit_events_device_id", "edge_device_audit_events", ["device_id"])
    op.create_index("ix_edge_device_audit_events_device_created", "edge_device_audit_events", ["device_id", "created_at"])

    op.create_table(
        "edge_device_request_nonces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("credential_id", sa.String(length=32), sa.ForeignKey("edge_device_credentials.credential_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("nonce_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_timestamp", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("credential_id", "nonce_sha256", name="uq_edge_device_nonce_credential_digest"),
        sa.CheckConstraint("length(nonce_sha256) = 64", name="ck_edge_device_nonce_digest"),
    )
    op.create_index("ix_edge_device_request_nonces_expires", "edge_device_request_nonces", ["expires_at"])

    op.create_table(
        "edge_device_event_cursors",
        sa.Column("device_id", sa.String(length=120), sa.ForeignKey("edge_devices.device_id", ondelete="RESTRICT"), primary_key=True, nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("last_sequence >= 0", name="ck_edge_device_cursor_nonnegative"),
    )

    op.create_table(
        "edge_device_event_inbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.String(length=120), sa.ForeignKey("edge_devices.device_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("shelf_id", sa.Integer(), sa.ForeignKey("shelves.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("device_id", "event_id", name="uq_edge_device_inbox_event"),
        sa.UniqueConstraint("device_id", "sequence_number", name="uq_edge_device_inbox_sequence"),
        sa.CheckConstraint("sequence_number > 0", name="ck_edge_device_inbox_sequence_positive"),
        sa.CheckConstraint("length(fingerprint_sha256) = 64", name="ck_edge_device_inbox_fingerprint"),
    )
    op.create_index("ix_edge_device_event_inbox_device_id", "edge_device_event_inbox", ["device_id"])
    op.create_index("ix_edge_device_event_inbox_store_received", "edge_device_event_inbox", ["store_id", "received_at"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_edge_device_append_only_mutation_0071()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'edge device audit and inbox records are append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        for table in ("edge_device_audit_events", "edge_device_event_inbox"):
            op.execute(
                f"CREATE TRIGGER trg_{table}_append_only_0071 "
                f"BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION prevent_edge_device_append_only_mutation_0071()"
            )
        op.execute("""
            CREATE OR REPLACE FUNCTION enforce_edge_device_identity_0071()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NEW.device_id IS DISTINCT FROM OLD.device_id
                   OR NEW.store_id IS DISTINCT FROM OLD.store_id
                   OR NEW.device_type IS DISTINCT FROM OLD.device_type
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at
                   OR (OLD.status = 'DISABLED' AND NEW.status IS DISTINCT FROM OLD.status)
                   OR (OLD.status = NEW.status AND NEW.disabled_at IS DISTINCT FROM OLD.disabled_at)
                   OR (OLD.status = 'ACTIVE' AND NEW.status = 'DISABLED' AND NEW.disabled_at IS NULL) THEN
                    RAISE EXCEPTION 'edge device identity and disablement are immutable'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_edge_device_identity_0071
            BEFORE UPDATE ON edge_devices
            FOR EACH ROW EXECUTE FUNCTION enforce_edge_device_identity_0071()
        """)
    elif bind.dialect.name == "sqlite":
        for table in ("edge_device_audit_events", "edge_device_event_inbox"):
            op.execute(f"""
                CREATE TRIGGER trg_{table}_no_update_0071
                BEFORE UPDATE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'edge device audit and inbox records are append-only');
                END
            """)
            op.execute(f"""
                CREATE TRIGGER trg_{table}_no_delete_0071
                BEFORE DELETE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'edge device audit and inbox records are append-only');
                END
            """)
        op.execute("""
            CREATE TRIGGER trg_edge_device_identity_0071
            BEFORE UPDATE ON edge_devices
            WHEN NEW.device_id <> OLD.device_id
              OR NEW.store_id <> OLD.store_id
              OR NEW.device_type <> OLD.device_type
              OR NEW.created_at <> OLD.created_at
              OR (OLD.status = 'DISABLED' AND NEW.status <> OLD.status)
              OR (OLD.status = NEW.status AND NEW.disabled_at IS NOT OLD.disabled_at)
              OR (OLD.status = 'ACTIVE' AND NEW.status = 'DISABLED' AND NEW.disabled_at IS NULL)
            BEGIN
                SELECT RAISE(ABORT, 'edge device identity and disablement are immutable');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in ("edge_device_audit_events", "edge_device_event_inbox"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only_0071 ON {table}")
        op.execute("DROP FUNCTION IF EXISTS prevent_edge_device_append_only_mutation_0071()")
        op.execute("DROP TRIGGER IF EXISTS trg_edge_device_identity_0071 ON edge_devices")
        op.execute("DROP FUNCTION IF EXISTS enforce_edge_device_identity_0071()")
    elif bind.dialect.name == "sqlite":
        for table in ("edge_device_audit_events", "edge_device_event_inbox"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update_0071")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete_0071")
        op.execute("DROP TRIGGER IF EXISTS trg_edge_device_identity_0071")

    op.drop_index("ix_edge_device_event_inbox_store_received", table_name="edge_device_event_inbox")
    op.drop_index("ix_edge_device_event_inbox_device_id", table_name="edge_device_event_inbox")
    op.drop_table("edge_device_event_inbox")
    op.drop_table("edge_device_event_cursors")
    op.drop_index("ix_edge_device_request_nonces_expires", table_name="edge_device_request_nonces")
    op.drop_table("edge_device_request_nonces")
    op.drop_index("ix_edge_device_audit_events_device_created", table_name="edge_device_audit_events")
    op.drop_index("ix_edge_device_audit_events_device_id", table_name="edge_device_audit_events")
    op.drop_table("edge_device_audit_events")
    op.drop_index("ix_edge_device_credentials_device_expiry", table_name="edge_device_credentials")
    op.drop_index("ix_edge_device_credentials_device_id", table_name="edge_device_credentials")
    op.drop_table("edge_device_credentials")
    op.drop_index("ix_edge_devices_store_status", table_name="edge_devices")
    op.drop_table("edge_devices")
