"""Audit administrative shelf-image purge scheduling transitions."""

from alembic import op

revision = "0032_shelf_image_purge_schedule_events"
down_revision = "0031_visual_ocr_evidence_append_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shelf_image_retention_events") as batch_op:
        batch_op.drop_constraint("ck_shelf_image_retention_event_type", type_="check")
        batch_op.create_check_constraint(
            "ck_shelf_image_retention_event_type",
            "event_type IN ('RESTRICTED', 'RESTORED', 'LEGAL_HOLD_APPLIED', "
            "'LEGAL_HOLD_RELEASED', 'PURGE_SCHEDULED', 'PURGE_CANCELLED')",
        )


def downgrade() -> None:
    with op.batch_alter_table("shelf_image_retention_events") as batch_op:
        batch_op.drop_constraint("ck_shelf_image_retention_event_type", type_="check")
        batch_op.create_check_constraint(
            "ck_shelf_image_retention_event_type",
            "event_type IN ('RESTRICTED', 'RESTORED', 'LEGAL_HOLD_APPLIED', 'LEGAL_HOLD_RELEASED')",
        )
