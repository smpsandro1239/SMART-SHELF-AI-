"""Transactional lifecycle for explicit Edge-device/task assignments."""
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models


class EdgeTaskAssignmentError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EdgeTaskAssignmentError(422, "TIMEZONE_REQUIRED", f"{field} tem de incluir fuso horário.")
    return value.astimezone(timezone.utc)


def _lock_store(db: Session, store_id: int) -> models.Store:
    row = db.query(models.Store).filter(models.Store.id == store_id).with_for_update().populate_existing().first()
    if row is None:
        raise EdgeTaskAssignmentError(404, "STORE_NOT_FOUND", "Loja não encontrada.")
    return row


def _lock_task(db: Session, task_id: int, store_id: int) -> models.ReplenishmentTask:
    row = (db.query(models.ReplenishmentTask)
        .filter(models.ReplenishmentTask.id == task_id, models.ReplenishmentTask.store_id == store_id)
        .with_for_update().populate_existing().first())
    if row is None:
        raise EdgeTaskAssignmentError(404, "TASK_NOT_FOUND", "Tarefa não encontrada.")
    return row


def _lock_device(db: Session, device_id: str, store_id: int) -> models.EdgeDevice:
    row = (db.query(models.EdgeDevice)
        .filter(models.EdgeDevice.device_id == device_id, models.EdgeDevice.store_id == store_id)
        .with_for_update().populate_existing().first())
    if row is None:
        raise EdgeTaskAssignmentError(404, "DEVICE_NOT_FOUND", "Dispositivo não encontrado.")
    return row


def _validate_actor(actor: models.User, store_id: int) -> None:
    if actor is None or not actor.is_active or actor.role not in {"ADMIN", "SUPERVISOR"}:
        raise EdgeTaskAssignmentError(403, "SUPERVISOR_REQUIRED", "É necessário um utilizador ADMIN ou SUPERVISOR activo.")
    if actor.role != "ADMIN" and actor.store_id != store_id:
        raise EdgeTaskAssignmentError(404, "STORE_NOT_FOUND", "Loja não encontrada.")


EDGE_TASK_ACTIONS = frozenset({"ACCEPTED", "STARTED", "COMPLETED"})


def _normalize_allowed_actions(value: list[str] | tuple[str, ...]) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise EdgeTaskAssignmentError(422, "INVALID_ALLOWED_ACTIONS", "allowed_actions tem de ser uma lista.")
    if any(type(action) is not str or action not in EDGE_TASK_ACTIONS for action in value):
        raise EdgeTaskAssignmentError(422, "INVALID_ALLOWED_ACTIONS", "allowed_actions contém uma acção inválida.")
    if len(value) != len(set(value)):
        raise EdgeTaskAssignmentError(422, "INVALID_ALLOWED_ACTIONS", "allowed_actions não pode conter duplicados.")
    return sorted(value)


def create_edge_task_assignment(
    db: Session, *, store_id: int, task_id: int, device_id: str, actor: models.User,
    reason: str, valid_from: datetime, valid_until: datetime | None = None,
    allowed_actions: list[str] | tuple[str, ...] = (),
) -> models.EdgeDeviceTaskAssignment:
    reason = reason.strip()
    allowed_actions = _normalize_allowed_actions(allowed_actions)
    if len(reason) < 3:
        raise EdgeTaskAssignmentError(422, "REASON_REQUIRED", "O motivo deve conter pelo menos três caracteres.")
    valid_from = _aware(valid_from, "valid_from")
    if valid_until is not None:
        valid_until = _aware(valid_until, "valid_until")
        if valid_until <= valid_from:
            raise EdgeTaskAssignmentError(422, "INVALID_VALIDITY_RANGE", "valid_until tem de ser posterior a valid_from.")

    try:
        _validate_actor(actor, store_id)
        _lock_store(db, store_id)
        task = _lock_task(db, task_id, store_id)
        device = _lock_device(db, device_id, store_id)
        if task.status not in {"PENDING", "ASSIGNED", "IN_PROGRESS"}:
            raise EdgeTaskAssignmentError(409, "TASK_NOT_ACTIVE", "Só é possível associar tarefas activas.")
        if device.status != "ACTIVE":
            raise EdgeTaskAssignmentError(409, "DEVICE_NOT_ACTIVE", "O dispositivo não está activo.")

        now = models.utc_now()
        assignment = models.EdgeDeviceTaskAssignment(
            store_id=store_id, task_id=task.id, device_id=device.device_id,
            task_version=task.task_version, valid_from=valid_from, valid_until=valid_until,
            created_by_user_id=actor.id, created_at=now,
        )
        db.add(assignment)
        db.flush()
        db.add(models.EdgeDeviceTaskAssignmentEvent(
            assignment_id=assignment.id, event_type="CREATED", actor_user_id=actor.id,
            reason=reason, details={
                "task_version": task.task_version,
                "device_id": device.device_id,
                "allowed_actions": allowed_actions,
            },
            created_at=now,
        ))
        db.commit()
        db.refresh(assignment)
        return assignment
    except EdgeTaskAssignmentError:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise EdgeTaskAssignmentError(409, "ACTIVE_ASSIGNMENT_EXISTS", "Já existe uma associação não revogada para este dispositivo e tarefa.") from exc
    except Exception:
        db.rollback()
        raise


def revoke_edge_task_assignment(
    db: Session, *, assignment_id: int, actor: models.User, reason: str,
) -> models.EdgeDeviceTaskAssignment:
    reason = reason.strip()
    if len(reason) < 3:
        raise EdgeTaskAssignmentError(422, "REASON_REQUIRED", "O motivo deve conter pelo menos três caracteres.")
    try:
        # Non-locking lookup only discovers immutable parent keys. All locks are
        # then acquired in the canonical Store -> Task -> Device -> Assignment order.
        identity = (db.query(
            models.EdgeDeviceTaskAssignment.store_id,
            models.EdgeDeviceTaskAssignment.task_id,
            models.EdgeDeviceTaskAssignment.device_id,
        ).filter(models.EdgeDeviceTaskAssignment.id == assignment_id).first())
        if identity is None:
            raise EdgeTaskAssignmentError(404, "ASSIGNMENT_NOT_FOUND", "Associação não encontrada.")
        store_id, task_id, device_id = identity
        _validate_actor(actor, store_id)
        _lock_store(db, store_id)
        _lock_task(db, task_id, store_id)
        _lock_device(db, device_id, store_id)
        assignment = (db.query(models.EdgeDeviceTaskAssignment)
            .filter(models.EdgeDeviceTaskAssignment.id == assignment_id,
                    models.EdgeDeviceTaskAssignment.store_id == store_id)
            .with_for_update().populate_existing().first())
        if assignment is None:
            raise EdgeTaskAssignmentError(404, "ASSIGNMENT_NOT_FOUND", "Associação não encontrada.")
        if assignment.revoked_at is not None:
            raise EdgeTaskAssignmentError(409, "ASSIGNMENT_ALREADY_REVOKED", "A associação já foi revogada.")
        now = models.utc_now()
        assignment.revoked_at = now
        assignment.revoked_by_user_id = actor.id
        assignment.revocation_reason = reason
        db.add(models.EdgeDeviceTaskAssignmentEvent(
            assignment_id=assignment.id, event_type="REVOKED", actor_user_id=actor.id,
            reason=reason, details={"task_version": assignment.task_version}, created_at=now,
        ))
        db.commit()
        db.refresh(assignment)
        return assignment
    except EdgeTaskAssignmentError:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise EdgeTaskAssignmentError(409, "ASSIGNMENT_CONFLICT", "A associação foi alterada concorrentemente.") from exc
    except Exception:
        db.rollback()
        raise
