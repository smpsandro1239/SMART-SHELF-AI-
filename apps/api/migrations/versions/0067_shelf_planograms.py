"""Versioned shelf planograms and immutable activated geometry."""
from alembic import op
import sqlalchemy as sa

revision = "0067_shelf_planograms"
down_revision = "0066_dataset_output_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shelf_planograms",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shelf_id", sa.Integer(), sa.ForeignKey("shelves.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
        sa.Column("calibration_source", sa.String(8), nullable=False, server_default="MANUAL"),
        sa.Column("calibration_image_id", sa.Integer(), sa.ForeignKey("shelf_images.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("calibration_image_sha256", sa.String(64), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activation_reason", sa.String(500), nullable=True),
        sa.Column("retired_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retirement_reason", sa.String(500), nullable=True),
        sa.UniqueConstraint("shelf_id", "version", name="uq_shelf_planogram_shelf_version"),
        sa.CheckConstraint("version > 0", name="ck_shelf_planogram_version_positive"),
        sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'RETIRED')", name="ck_shelf_planogram_status"),
        sa.CheckConstraint("calibration_source IN ('MANUAL', 'IMAGE')", name="ck_shelf_planogram_calibration_source"),
        sa.CheckConstraint(
            "(calibration_source = 'MANUAL' AND calibration_image_id IS NULL AND calibration_image_sha256 IS NULL) "
            "OR (calibration_source = 'IMAGE' AND calibration_image_id IS NOT NULL AND length(calibration_image_sha256) = 64)",
            name="ck_shelf_planogram_calibration_reference",
        ),
        sa.CheckConstraint(
            "(activated_by_user_id IS NULL AND activated_at IS NULL AND activation_reason IS NULL) "
            "OR (activated_by_user_id IS NOT NULL AND activated_at IS NOT NULL AND activation_reason IS NOT NULL AND length(trim(activation_reason)) > 0)",
            name="ck_shelf_planogram_activation_metadata",
        ),
        sa.CheckConstraint(
            "(retired_by_user_id IS NULL AND retired_at IS NULL AND retirement_reason IS NULL) "
            "OR (retired_by_user_id IS NOT NULL AND retired_at IS NOT NULL AND retirement_reason IS NOT NULL AND length(trim(retirement_reason)) > 0)",
            name="ck_shelf_planogram_retirement_metadata",
        ),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND activated_at IS NULL AND retired_at IS NULL) "
            "OR (status = 'ACTIVE' AND activated_at IS NOT NULL AND retired_at IS NULL) "
            "OR (status = 'RETIRED' AND activated_at IS NOT NULL AND retired_at IS NOT NULL)",
            name="ck_shelf_planogram_status_timestamps",
        ),
        sa.CheckConstraint("activated_at IS NULL OR activated_at >= created_at", name="ck_shelf_planogram_activation_after_creation"),
        sa.CheckConstraint("retired_at IS NULL OR retired_at >= activated_at", name="ck_shelf_planogram_retirement_after_activation"),
    )
    op.create_index("ix_shelf_planograms_shelf_id", "shelf_planograms", ["shelf_id"])
    op.create_index("ix_shelf_planograms_status", "shelf_planograms", ["status"])
    op.create_index(
        "uq_shelf_planogram_one_active_per_shelf",
        "shelf_planograms",
        ["shelf_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index("ix_shelf_planograms_calibration_image_id", "shelf_planograms", ["calibration_image_id"])
    op.create_index(
        "ix_shelf_planograms_shelf_status_version",
        "shelf_planograms",
        ["shelf_id", "status", "version"],
    )

    op.create_table(
        "shelf_planogram_cells",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("planogram_id", sa.Integer(), sa.ForeignKey("shelf_planograms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cell_code", sa.String(80), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("column_index", sa.Integer(), nullable=False),
        sa.Column("x_min", sa.Float(), nullable=False),
        sa.Column("y_min", sa.Float(), nullable=False),
        sa.Column("x_max", sa.Float(), nullable=False),
        sa.Column("y_max", sa.Float(), nullable=False),
        sa.Column("expected_product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("planogram_id", "cell_code", name="uq_shelf_planogram_cell_code"),
        sa.UniqueConstraint("planogram_id", "row_index", "column_index", name="uq_shelf_planogram_cell_grid_position"),
        sa.CheckConstraint("row_index >= 0 AND column_index >= 0", name="ck_shelf_planogram_cell_grid_nonnegative"),
        sa.CheckConstraint("length(trim(cell_code)) > 0", name="ck_shelf_planogram_cell_code_nonempty"),
        sa.CheckConstraint(
            "x_min >= 0 AND x_min < x_max AND x_max <= 1 "
            "AND y_min >= 0 AND y_min < y_max AND y_max <= 1",
            name="ck_shelf_planogram_cell_bbox_normalized",
        ),
    )
    op.create_index("ix_shelf_planogram_cells_planogram_id", "shelf_planogram_cells", ["planogram_id"])
    op.create_index("ix_shelf_planogram_cells_expected_product_id", "shelf_planogram_cells", ["expected_product_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION guard_shelf_planogram_0067()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE expected_version INTEGER; actor_active BOOLEAN; source_ok BOOLEAN;
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    PERFORM id FROM shelves WHERE id = NEW.shelf_id FOR UPDATE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'planogram shelf does not exist' USING ERRCODE = '23503';
                    END IF;
                    SELECT COALESCE(MAX(version), 0) + 1 INTO expected_version
                    FROM shelf_planograms WHERE shelf_id = NEW.shelf_id;
                    IF NEW.version <> expected_version THEN
                        RAISE EXCEPTION 'planogram version must be consecutive' USING ERRCODE = '23514';
                    END IF;
                    SELECT is_active INTO actor_active FROM users WHERE id = NEW.created_by_user_id;
                    IF actor_active IS DISTINCT FROM TRUE THEN
                        RAISE EXCEPTION 'planogram requires an active creator' USING ERRCODE = '23514';
                    END IF;
                    IF NEW.status <> 'DRAFT' OR NEW.activated_by_user_id IS NOT NULL
                       OR NEW.activated_at IS NOT NULL OR NEW.activation_reason IS NOT NULL
                       OR NEW.retired_by_user_id IS NOT NULL OR NEW.retired_at IS NOT NULL
                       OR NEW.retirement_reason IS NOT NULL THEN
                        RAISE EXCEPTION 'new planograms must start as clean DRAFT versions' USING ERRCODE = '23514';
                    END IF;
                    IF NEW.calibration_source = 'IMAGE' THEN
                        SELECT EXISTS (
                            SELECT 1 FROM shelf_images
                            WHERE id = NEW.calibration_image_id
                              AND shelf_id = NEW.shelf_id
                              AND sha256 = NEW.calibration_image_sha256
                              AND retention_status = 'ACTIVE'
                        ) INTO source_ok;
                        IF NOT source_ok THEN
                            RAISE EXCEPTION 'planogram calibration image is not eligible' USING ERRCODE = '23514';
                        END IF;
                    END IF;
                    RETURN NEW;
                ELSIF TG_OP = 'UPDATE' THEN
                    IF NEW.shelf_id IS DISTINCT FROM OLD.shelf_id
                       OR NEW.version IS DISTINCT FROM OLD.version
                       OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
                       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                        RAISE EXCEPTION 'planogram identity is immutable' USING ERRCODE = '23514';
                    END IF;
                    IF OLD.status = 'DRAFT' AND NEW.status = 'DRAFT' THEN
                        IF NEW.activated_by_user_id IS NOT NULL OR NEW.activated_at IS NOT NULL
                           OR NEW.activation_reason IS NOT NULL OR NEW.retired_by_user_id IS NOT NULL
                           OR NEW.retired_at IS NOT NULL OR NEW.retirement_reason IS NOT NULL THEN
                            RAISE EXCEPTION 'DRAFT planogram cannot carry lifecycle metadata' USING ERRCODE = '23514';
                        END IF;
                        IF NEW.calibration_source = 'IMAGE' THEN
                            SELECT EXISTS (
                                SELECT 1 FROM shelf_images
                                WHERE id = NEW.calibration_image_id
                                  AND shelf_id = NEW.shelf_id
                                  AND sha256 = NEW.calibration_image_sha256
                                  AND retention_status = 'ACTIVE'
                            ) INTO source_ok;
                            IF NOT source_ok THEN
                                RAISE EXCEPTION 'planogram calibration image is not eligible' USING ERRCODE = '23514';
                            END IF;
                        END IF;
                        RETURN NEW;
                    ELSIF OLD.status = 'DRAFT' AND NEW.status = 'ACTIVE' THEN
                        SELECT is_active INTO actor_active FROM users WHERE id = NEW.activated_by_user_id;
                        IF actor_active IS DISTINCT FROM TRUE OR NEW.activated_at IS NULL
                           OR NEW.activation_reason IS NULL OR length(trim(NEW.activation_reason)) = 0
                           OR NEW.retired_by_user_id IS NOT NULL OR NEW.retired_at IS NOT NULL
                           OR NEW.retirement_reason IS NOT NULL THEN
                            RAISE EXCEPTION 'activation requires an active actor, timestamp and reason' USING ERRCODE = '23514';
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM shelf_planogram_cells WHERE planogram_id = NEW.id) THEN
                            RAISE EXCEPTION 'planogram activation requires at least one cell' USING ERRCODE = '23514';
                        END IF;
                        IF NEW.calibration_source = 'IMAGE' THEN
                            SELECT EXISTS (
                                SELECT 1 FROM shelf_images
                                WHERE id = NEW.calibration_image_id
                                  AND shelf_id = NEW.shelf_id
                                  AND sha256 = NEW.calibration_image_sha256
                                  AND retention_status = 'ACTIVE'
                            ) INTO source_ok;
                            IF NOT source_ok THEN
                                RAISE EXCEPTION 'planogram calibration image is not eligible' USING ERRCODE = '23514';
                            END IF;
                        END IF;
                        RETURN NEW;
                    ELSIF OLD.status = 'ACTIVE' AND NEW.status = 'RETIRED' THEN
                        SELECT is_active INTO actor_active FROM users WHERE id = NEW.retired_by_user_id;
                        IF actor_active IS DISTINCT FROM TRUE OR NEW.retired_at IS NULL
                           OR NEW.retirement_reason IS NULL OR length(trim(NEW.retirement_reason)) = 0
                           OR NEW.activated_by_user_id IS DISTINCT FROM OLD.activated_by_user_id
                           OR NEW.activated_at IS DISTINCT FROM OLD.activated_at
                           OR NEW.activation_reason IS DISTINCT FROM OLD.activation_reason
                           OR NEW.calibration_source IS DISTINCT FROM OLD.calibration_source
                           OR NEW.calibration_image_id IS DISTINCT FROM OLD.calibration_image_id
                           OR NEW.calibration_image_sha256 IS DISTINCT FROM OLD.calibration_image_sha256 THEN
                            RAISE EXCEPTION 'retirement requires an active actor and preserves planogram identity' USING ERRCODE = '23514';
                        END IF;
                        RETURN NEW;
                    END IF;
                    RAISE EXCEPTION 'invalid planogram lifecycle transition' USING ERRCODE = '23514';
                ELSIF TG_OP = 'DELETE' THEN
                    IF OLD.status <> 'DRAFT' THEN
                        RAISE EXCEPTION 'activated planogram history cannot be deleted' USING ERRCODE = '23514';
                    END IF;
                    RETURN OLD;
                END IF;
                RETURN NULL;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_planogram_guard_0067
            BEFORE INSERT OR UPDATE OR DELETE ON shelf_planograms
            FOR EACH ROW EXECUTE FUNCTION guard_shelf_planogram_0067()
        """)
        op.execute("""
            CREATE FUNCTION guard_shelf_planogram_cell_0067()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE parent_status TEXT; parent_shelf_id INTEGER; overlap_found BOOLEAN;
            BEGIN
                IF TG_OP = 'UPDATE' THEN
                    SELECT status INTO parent_status FROM shelf_planograms
                    WHERE id = OLD.planogram_id FOR UPDATE;
                    IF parent_status IS DISTINCT FROM 'DRAFT' THEN
                        RAISE EXCEPTION 'only DRAFT planograms can change cells' USING ERRCODE = '23514';
                    END IF;
                END IF;
                SELECT status, shelf_id INTO parent_status, parent_shelf_id
                FROM shelf_planograms WHERE id = NEW.planogram_id FOR UPDATE;
                IF parent_status IS DISTINCT FROM 'DRAFT' THEN
                    RAISE EXCEPTION 'only DRAFT planograms can change cells' USING ERRCODE = '23514';
                END IF;
                IF NEW.expected_product_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM shelf_products sp
                    JOIN products p ON p.id = sp.product_id
                    WHERE sp.shelf_id = parent_shelf_id
                      AND sp.product_id = NEW.expected_product_id
                      AND p.is_active = TRUE
                ) THEN
                    RAISE EXCEPTION 'expected SKU must be active and assigned to the planogram shelf' USING ERRCODE = '23514';
                END IF;
                SELECT EXISTS (
                    SELECT 1 FROM shelf_planogram_cells c
                    WHERE c.planogram_id = NEW.planogram_id
                      AND c.id <> COALESCE(NEW.id, -1)
                      AND c.x_min < NEW.x_max AND c.x_max > NEW.x_min
                      AND c.y_min < NEW.y_max AND c.y_max > NEW.y_min
                ) INTO overlap_found;
                IF overlap_found THEN
                    RAISE EXCEPTION 'planogram cells must not overlap' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_planogram_cell_guard_0067
            BEFORE INSERT OR UPDATE ON shelf_planogram_cells
            FOR EACH ROW EXECUTE FUNCTION guard_shelf_planogram_cell_0067()
        """)
        op.execute("""
            CREATE FUNCTION guard_shelf_planogram_cell_delete_0067()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE parent_status TEXT;
            BEGIN
                SELECT status INTO parent_status FROM shelf_planograms
                WHERE id = OLD.planogram_id FOR UPDATE;
                IF parent_status IS DISTINCT FROM 'DRAFT' THEN
                    RAISE EXCEPTION 'only DRAFT planograms can change cells' USING ERRCODE = '23514';
                END IF;
                RETURN OLD;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_planogram_cell_delete_0067
            BEFORE DELETE ON shelf_planogram_cells
            FOR EACH ROW EXECUTE FUNCTION guard_shelf_planogram_cell_delete_0067()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_shelf_planogram_insert_guard_0067
            BEFORE INSERT ON shelf_planograms
            BEGIN
                SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM shelves WHERE id = NEW.shelf_id)
                    THEN RAISE(ABORT, 'planogram shelf does not exist') END;
                SELECT CASE WHEN NEW.version <> (
                    SELECT COALESCE(MAX(version), 0) + 1 FROM shelf_planograms WHERE shelf_id = NEW.shelf_id
                ) THEN RAISE(ABORT, 'planogram version must be consecutive') END;
                SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.created_by_user_id AND is_active = 1)
                    THEN RAISE(ABORT, 'planogram requires an active creator') END;
                SELECT CASE WHEN NEW.status <> 'DRAFT'
                    OR NEW.activated_by_user_id IS NOT NULL OR NEW.activated_at IS NOT NULL
                    OR NEW.activation_reason IS NOT NULL OR NEW.retired_by_user_id IS NOT NULL
                    OR NEW.retired_at IS NOT NULL OR NEW.retirement_reason IS NOT NULL
                    THEN RAISE(ABORT, 'new planograms must start as clean DRAFT versions') END;
                SELECT CASE WHEN NEW.calibration_source = 'IMAGE' AND NOT EXISTS (
                    SELECT 1 FROM shelf_images
                    WHERE id = NEW.calibration_image_id AND shelf_id = NEW.shelf_id
                      AND sha256 = NEW.calibration_image_sha256 AND retention_status = 'ACTIVE'
                ) THEN RAISE(ABORT, 'planogram calibration image is not eligible') END;
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_planogram_update_guard_0067
            BEFORE UPDATE ON shelf_planograms
            BEGIN
                SELECT CASE WHEN NEW.shelf_id IS NOT OLD.shelf_id OR NEW.version IS NOT OLD.version
                    OR NEW.created_by_user_id IS NOT OLD.created_by_user_id OR NEW.created_at IS NOT OLD.created_at
                    THEN RAISE(ABORT, 'planogram identity is immutable') END;
                SELECT CASE WHEN NOT (
                    (OLD.status = 'DRAFT' AND NEW.status = 'DRAFT')
                    OR (OLD.status = 'DRAFT' AND NEW.status = 'ACTIVE'
                        AND NEW.activated_by_user_id IS NOT NULL AND NEW.activated_at IS NOT NULL
                        AND NEW.activation_reason IS NOT NULL AND length(trim(NEW.activation_reason)) > 0
                        AND NEW.retired_by_user_id IS NULL AND NEW.retired_at IS NULL AND NEW.retirement_reason IS NULL)
                    OR (OLD.status = 'ACTIVE' AND NEW.status = 'RETIRED'
                        AND NEW.retired_by_user_id IS NOT NULL AND NEW.retired_at IS NOT NULL
                        AND NEW.retirement_reason IS NOT NULL AND length(trim(NEW.retirement_reason)) > 0
                        AND NEW.activated_by_user_id IS OLD.activated_by_user_id
                        AND NEW.activated_at IS OLD.activated_at
                        AND NEW.activation_reason IS OLD.activation_reason
                        AND NEW.calibration_source IS OLD.calibration_source
                        AND NEW.calibration_image_id IS OLD.calibration_image_id
                        AND NEW.calibration_image_sha256 IS OLD.calibration_image_sha256)
                ) THEN RAISE(ABORT, 'invalid planogram lifecycle transition') END;
                SELECT CASE WHEN OLD.status = 'DRAFT' AND NEW.status = 'DRAFT'
                    AND (NEW.activated_by_user_id IS NOT NULL OR NEW.activated_at IS NOT NULL
                         OR NEW.activation_reason IS NOT NULL OR NEW.retired_by_user_id IS NOT NULL
                         OR NEW.retired_at IS NOT NULL OR NEW.retirement_reason IS NOT NULL)
                    THEN RAISE(ABORT, 'DRAFT planogram cannot carry lifecycle metadata') END;
                SELECT CASE WHEN OLD.status = 'DRAFT' AND NEW.status = 'ACTIVE'
                    AND NOT EXISTS (SELECT 1 FROM shelf_planogram_cells WHERE planogram_id = NEW.id)
                    THEN RAISE(ABORT, 'planogram activation requires at least one cell') END;
                SELECT CASE WHEN NEW.status = 'ACTIVE' AND NOT EXISTS (
                    SELECT 1 FROM users WHERE id = NEW.activated_by_user_id AND is_active = 1
                ) THEN RAISE(ABORT, 'activation requires an active actor') END;
                SELECT CASE WHEN NEW.status = 'RETIRED' AND NOT EXISTS (
                    SELECT 1 FROM users WHERE id = NEW.retired_by_user_id AND is_active = 1
                ) THEN RAISE(ABORT, 'retirement requires an active actor') END;
                SELECT CASE WHEN NEW.calibration_source = 'IMAGE' AND NOT EXISTS (
                    SELECT 1 FROM shelf_images
                    WHERE id = NEW.calibration_image_id AND shelf_id = NEW.shelf_id
                      AND sha256 = NEW.calibration_image_sha256 AND retention_status = 'ACTIVE'
                ) THEN RAISE(ABORT, 'planogram calibration image is not eligible') END;
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_planogram_delete_guard_0067
            BEFORE DELETE ON shelf_planograms
            WHEN OLD.status <> 'DRAFT'
            BEGIN
                SELECT RAISE(ABORT, 'activated planogram history cannot be deleted');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_planogram_cell_insert_guard_0067
            BEFORE INSERT ON shelf_planogram_cells
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM shelf_planograms WHERE id = NEW.planogram_id AND status = 'DRAFT'
                ) THEN RAISE(ABORT, 'only DRAFT planograms can change cells') END;
                SELECT CASE WHEN NEW.expected_product_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM shelf_planograms spg
                    JOIN shelf_products sp ON sp.shelf_id = spg.shelf_id
                    JOIN products p ON p.id = sp.product_id
                    WHERE spg.id = NEW.planogram_id AND sp.product_id = NEW.expected_product_id
                      AND p.is_active = 1
                ) THEN RAISE(ABORT, 'expected SKU must be active and assigned to the planogram shelf') END;
                SELECT CASE WHEN EXISTS (
                    SELECT 1 FROM shelf_planogram_cells c
                    WHERE c.planogram_id = NEW.planogram_id
                      AND c.x_min < NEW.x_max AND c.x_max > NEW.x_min
                      AND c.y_min < NEW.y_max AND c.y_max > NEW.y_min
                ) THEN RAISE(ABORT, 'planogram cells must not overlap') END;
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_planogram_cell_update_guard_0067
            BEFORE UPDATE ON shelf_planogram_cells
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM shelf_planograms WHERE id = OLD.planogram_id AND status = 'DRAFT'
                ) THEN RAISE(ABORT, 'only DRAFT planograms can change cells') END;
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM shelf_planograms WHERE id = NEW.planogram_id AND status = 'DRAFT'
                ) THEN RAISE(ABORT, 'only DRAFT planograms can change cells') END;
                SELECT CASE WHEN NEW.expected_product_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM shelf_planograms spg
                    JOIN shelf_products sp ON sp.shelf_id = spg.shelf_id
                    JOIN products p ON p.id = sp.product_id
                    WHERE spg.id = NEW.planogram_id AND sp.product_id = NEW.expected_product_id
                      AND p.is_active = 1
                ) THEN RAISE(ABORT, 'expected SKU must be active and assigned to the planogram shelf') END;
                SELECT CASE WHEN EXISTS (
                    SELECT 1 FROM shelf_planogram_cells c
                    WHERE c.planogram_id = NEW.planogram_id AND c.id <> NEW.id
                      AND c.x_min < NEW.x_max AND c.x_max > NEW.x_min
                      AND c.y_min < NEW.y_max AND c.y_max > NEW.y_min
                ) THEN RAISE(ABORT, 'planogram cells must not overlap') END;
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_planogram_cell_delete_guard_0067
            BEFORE DELETE ON shelf_planogram_cells
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM shelf_planograms WHERE id = OLD.planogram_id AND status = 'DRAFT'
                ) THEN RAISE(ABORT, 'only DRAFT planograms can change cells') END;
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_planogram_cell_delete_0067 ON shelf_planogram_cells")
        op.execute("DROP FUNCTION IF EXISTS guard_shelf_planogram_cell_delete_0067()")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_planogram_cell_guard_0067 ON shelf_planogram_cells")
        op.execute("DROP FUNCTION IF EXISTS guard_shelf_planogram_cell_0067()")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_planogram_guard_0067 ON shelf_planograms")
        op.execute("DROP FUNCTION IF EXISTS guard_shelf_planogram_0067()")
    elif bind.dialect.name == "sqlite":
        for name in (
            "trg_shelf_planogram_cell_delete_guard_0067",
            "trg_shelf_planogram_cell_update_guard_0067",
            "trg_shelf_planogram_cell_insert_guard_0067",
            "trg_shelf_planogram_delete_guard_0067",
            "trg_shelf_planogram_update_guard_0067",
            "trg_shelf_planogram_insert_guard_0067",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("ix_shelf_planogram_cells_expected_product_id", table_name="shelf_planogram_cells")
    op.drop_index("ix_shelf_planogram_cells_planogram_id", table_name="shelf_planogram_cells")
    op.drop_table("shelf_planogram_cells")
    op.drop_index("ix_shelf_planograms_calibration_image_id", table_name="shelf_planograms")
    op.drop_index("ix_shelf_planograms_shelf_status_version", table_name="shelf_planograms")
    op.drop_index("uq_shelf_planogram_one_active_per_shelf", table_name="shelf_planograms")
    op.drop_index("ix_shelf_planograms_status", table_name="shelf_planograms")
    op.drop_index("ix_shelf_planograms_shelf_id", table_name="shelf_planograms")
    op.drop_table("shelf_planograms")
