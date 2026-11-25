"""Add store scope to users and account-linked task assignments."""
from alembic import op
import sqlalchemy as sa

revision = "0006_user_store_task_assignee"
down_revision = "0005_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("store_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_users_store_id_stores", "users", "stores",
        ["store_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_users_store_id", "users", ["store_id"])
    op.add_column("replenishment_tasks", sa.Column("assigned_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_replenishment_tasks_assigned_user_id_users",
        "replenishment_tasks", "users", ["assigned_user_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_replenishment_tasks_assigned_user_id", "replenishment_tasks", ["assigned_user_id"])


def downgrade() -> None:
    op.drop_index("ix_replenishment_tasks_assigned_user_id", table_name="replenishment_tasks")
    op.drop_constraint("fk_replenishment_tasks_assigned_user_id_users", "replenishment_tasks", type_="foreignkey")
    op.drop_column("replenishment_tasks", "assigned_user_id")
    op.drop_index("ix_users_store_id", table_name="users")
    op.drop_constraint("fk_users_store_id_stores", "users", type_="foreignkey")
    op.drop_column("users", "store_id")
