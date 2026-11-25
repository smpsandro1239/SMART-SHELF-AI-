"""Persist employee shifts, competencies and availability."""

from alembic import op
import sqlalchemy as sa


revision = "0074_employee_workforce"
down_revision = "0073_edge_event_processing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employee_shifts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("break_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(12), nullable=False, server_default="SCHEDULED"),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("ends_at > starts_at", name="ck_employee_shift_time_range"),
        sa.CheckConstraint("break_minutes >= 0", name="ck_employee_shift_break_nonnegative"),
        sa.CheckConstraint("status IN ('SCHEDULED', 'CANCELLED')", name="ck_employee_shift_status"),
    )
    op.create_index("ix_employee_shifts_store_start", "employee_shifts", ["store_id", "starts_at"])
    op.create_index("ix_employee_shifts_employee_start", "employee_shifts", ["employee_id", "starts_at"])

    op.create_table(
        "employee_skills",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_code", sa.String(60), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("employee_id", "skill_code", name="uq_employee_skill_code"),
        sa.CheckConstraint("level BETWEEN 1 AND 5", name="ck_employee_skill_level"),
    )
    op.create_index("ix_employee_skills_store_code", "employee_skills", ["store_id", "skill_code"])

    op.create_table(
        "employee_availability",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("ends_at > starts_at", name="ck_employee_availability_time_range"),
        sa.CheckConstraint("status IN ('AVAILABLE', 'UNAVAILABLE')", name="ck_employee_availability_status"),
    )
    op.create_index("ix_employee_availability_employee_start", "employee_availability", ["employee_id", "starts_at"])
    op.create_index("ix_employee_availability_store_start", "employee_availability", ["store_id", "starts_at"])


def downgrade() -> None:
    op.drop_index("ix_employee_availability_store_start", table_name="employee_availability")
    op.drop_index("ix_employee_availability_employee_start", table_name="employee_availability")
    op.drop_table("employee_availability")
    op.drop_index("ix_employee_skills_store_code", table_name="employee_skills")
    op.drop_table("employee_skills")
    op.drop_index("ix_employee_shifts_employee_start", table_name="employee_shifts")
    op.drop_index("ix_employee_shifts_store_start", table_name="employee_shifts")
    op.drop_table("employee_shifts")
