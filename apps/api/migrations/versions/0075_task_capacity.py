"""Add task duration estimates and competency requirements."""

from alembic import op
import sqlalchemy as sa


revision = "0075_task_capacity"
down_revision = "0074_employee_workforce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "replenishment_tasks",
        sa.Column("estimated_duration_minutes", sa.Integer(), nullable=False, server_default="15"),
    )
    op.add_column(
        "replenishment_tasks",
        sa.Column("required_skill_code", sa.String(60), nullable=True),
    )
    op.create_check_constraint(
        "ck_task_estimated_duration_positive",
        "replenishment_tasks",
        "estimated_duration_minutes BETWEEN 1 AND 480",
    )


def downgrade() -> None:
    op.drop_constraint("ck_task_estimated_duration_positive", "replenishment_tasks", type_="check")
    op.drop_column("replenishment_tasks", "required_skill_code")
    op.drop_column("replenishment_tasks", "estimated_duration_minutes")
