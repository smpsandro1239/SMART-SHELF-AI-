"""Allow CREATED as a structured task audit event."""
from alembic import op

revision = "0019_task_created_audit_event"
down_revision = "0018_task_lifecycle_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode keeps this constraint migration compatible with SQLite tests
    # and PostgreSQL deployments.
    with op.batch_alter_table("replenishment_task_events") as batch:
        batch.drop_constraint("ck_task_event_type", type_="check")
        batch.create_check_constraint(
            "ck_task_event_type",
            "event_type IN ('CREATED', 'APPROVED', 'STATUS_CHANGED')",
        )


def downgrade() -> None:
    with op.batch_alter_table("replenishment_task_events") as batch:
        batch.drop_constraint("ck_task_event_type", type_="check")
        batch.create_check_constraint(
            "ck_task_event_type",
            "event_type IN ('APPROVED', 'STATUS_CHANGED')",
        )
