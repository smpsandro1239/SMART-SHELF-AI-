"""Deterministic replenishment policies separated from computer-vision inference.

These functions produce suggestions only. They do not create stock movements,
purchase orders, or operational tasks.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
import math


def _quantity(name: str, value: float, *, allow_zero: bool = True) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    result = Decimal(str(value))
    if result < 0 or (not allow_zero and result == 0):
        qualifier = "positive" if not allow_zero else "non-negative"
        raise ValueError(f"{name} must be {qualifier}")
    return result


@dataclass(frozen=True)
class ShelfRefillInput:
    shelf_quantity: float
    target_quantity: float
    min_display_quantity: float
    backroom_available_quantity: float | None
    observation_confidence: float | None
    observation_age_minutes: float
    max_observation_age_minutes: float = 15.0
    min_confidence: float = 0.60


@dataclass(frozen=True)
class ShelfRefillDecision:
    status: str
    suggested_quantity: float | None
    shelf_gap_quantity: float
    remaining_gap_quantity: float
    requires_human_review: bool
    explanation: str


def suggest_shelf_refill(data: ShelfRefillInput) -> ShelfRefillDecision:
    """Suggest a shelf refill only when the visual evidence is fresh and credible."""
    shelf_qty = _quantity("shelf_quantity", data.shelf_quantity)
    target = _quantity("target_quantity", data.target_quantity, allow_zero=False)
    minimum = _quantity("min_display_quantity", data.min_display_quantity)
    age = _quantity("observation_age_minutes", data.observation_age_minutes)
    max_age = _quantity("max_observation_age_minutes", data.max_observation_age_minutes)
    if minimum > target:
        raise ValueError("min_display_quantity cannot exceed target_quantity")
    if data.min_confidence < 0 or data.min_confidence > 1:
        raise ValueError("min_confidence must be between 0 and 1")
    if data.observation_confidence is not None and (
        not math.isfinite(data.observation_confidence)
        or not 0 <= data.observation_confidence <= 1
    ):
        raise ValueError("observation_confidence must be between 0 and 1")

    gap = max(Decimal("0"), target - shelf_qty)
    if age > max_age:
        return ShelfRefillDecision(
            "STALE_OBSERVATION", None, float(gap), float(gap), True,
            "A observação visual expirou; é necessária uma nova captura.",
        )
    if data.observation_confidence is None or data.observation_confidence < data.min_confidence:
        return ShelfRefillDecision(
            "LOW_CONFIDENCE", None, float(gap), float(gap), True,
            "A confiança visual é insuficiente; requer confirmação humana.",
        )
    if shelf_qty > minimum:
        return ShelfRefillDecision(
            "NO_ACTION", 0.0, float(gap), float(gap), False,
            "A quantidade observada ainda não atingiu o limiar mínimo de exposição.",
        )
    if gap <= 0:
        return ShelfRefillDecision(
            "NO_ACTION", 0.0, 0.0, 0.0, False,
            "A prateleira já atingiu a quantidade-alvo.",
        )
    if data.backroom_available_quantity is None:
        return ShelfRefillDecision(
            "INVENTORY_UNKNOWN", None, float(gap), float(gap), True,
            "Não existe stock de retaguarda fiável; confirmar inventário antes da reposição.",
        )

    available = _quantity("backroom_available_quantity", data.backroom_available_quantity)
    if available == 0:
        return ShelfRefillDecision(
            "BACKROOM_OUT_OF_STOCK", 0.0, float(gap), float(gap), True,
            "A prateleira precisa de reposição, mas não existe stock disponível na retaguarda.",
        )

    refill = min(gap, available)
    remaining = gap - refill
    explanation = (
        "Reposição parcial: o stock disponível não cobre toda a diferença até à quantidade-alvo."
        if remaining > 0
        else "Reposição sugerida até à quantidade-alvo da prateleira."
    )
    return ShelfRefillDecision(
        "NEEDS_REPLENISHMENT", float(refill), float(gap), float(remaining),
        True, explanation,
    )


@dataclass(frozen=True)
class PurchaseReorderInput:
    on_hand_quantity: float
    reserved_quantity: float
    incoming_quantity: float
    demand_until_receipt: float
    reorder_point: float
    target_max_quantity: float
    minimum_order_quantity: float = 1.0
    pack_multiple: float = 1.0


@dataclass(frozen=True)
class PurchaseReorderDecision:
    status: str
    projected_stock_at_receipt: float
    suggested_order_quantity: float
    quantity_after_order: float
    explanation: str


def suggest_purchase_reorder(data: PurchaseReorderInput) -> PurchaseReorderDecision:
    """Calculate a supplier/warehouse reorder proposal from projected stock.

    Projected stock includes on-hand, incoming, reservations and demand expected
    before receipt. The order quantity restores the target level and is rounded
    up to the supplier's minimum quantity and pack multiple.
    """
    on_hand = _quantity("on_hand_quantity", data.on_hand_quantity)
    reserved = _quantity("reserved_quantity", data.reserved_quantity)
    incoming = _quantity("incoming_quantity", data.incoming_quantity)
    demand = _quantity("demand_until_receipt", data.demand_until_receipt)
    reorder_point = _quantity("reorder_point", data.reorder_point)
    target = _quantity("target_max_quantity", data.target_max_quantity, allow_zero=False)
    minimum_order = _quantity("minimum_order_quantity", data.minimum_order_quantity, allow_zero=False)
    multiple = _quantity("pack_multiple", data.pack_multiple, allow_zero=False)
    if reserved > on_hand:
        raise ValueError("reserved_quantity cannot exceed on_hand_quantity")
    if target <= reorder_point:
        raise ValueError("target_max_quantity must exceed reorder_point")

    projected = on_hand + incoming - reserved - demand
    if projected >= reorder_point:
        return PurchaseReorderDecision(
            "NO_ORDER", float(projected), 0.0, float(projected),
            "O stock projetado até à receção não desce abaixo do ponto de encomenda.",
        )

    raw_quantity = max(Decimal("0"), target - projected)
    required = max(raw_quantity, minimum_order)
    packs = (required / multiple).to_integral_value(rounding=ROUND_CEILING)
    order_quantity = packs * multiple
    return PurchaseReorderDecision(
        "ORDER_RECOMMENDED", float(projected), float(order_quantity),
        float(projected + order_quantity),
        "Proposta calculada para repor o nível-alvo, respeitando quantidade mínima e múltiplo de embalagem.",
    )
