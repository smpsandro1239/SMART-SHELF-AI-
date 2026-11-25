"""Enforce at most one active replenishment task per shelf and product."""
from alembic import op
import sqlalchemy as sa

revision = "0020_active_task_unique_index"
down_revision = "0019_task_created_audit_event"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_active_task_store_shelf_product"
ACTIVE_STATUSES = "('PENDING', 'ASSIGNED', 'IN_PROGRESS')"


def upgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            """
            SELECT store_id, shelf_id, product_id, COUNT(*) AS task_count
            FROM replenishment_tasks
            WHERE status IN ('PENDING', 'ASSIGNED', 'IN_PROGRESS')
            GROUP BY store_id, shelf_id, product_id
            HAVING COUNT(*) > 1
            ORDER BY store_id, shelf_id, product_id
            LIMIT 10
            """
        )
    ).mappings().all()
    if duplicates:
        sample = [dict(row) for row in duplicates]
        raise RuntimeError(
            "Cannot create the active-task unique index: existing duplicate active "
            f"tasks must be resolved first. Sample groups: {sample}"
        )

    op.create_index(
        INDEX_NAME,
        "replenishment_tasks",
        ["store_id", "shelf_id", "product_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN {ACTIVE_STATUSES}"),
        sqlite_where=sa.text(f"status IN {ACTIVE_STATUSES}"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="replenishment_tasks")
