"""Idempotent OCR catalogue matching and visual/text evidence fusion.

This service is shared by the background worker and API workflows. It only
creates immutable suggestions; it never confirms a SKU or changes inventory.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import models
from app.product_evidence_fusion import fuse_product_evidence
from app.product_matching import ProductMatch
from app.product_text import (
    CatalogueProduct,
    OCRText,
    TextCandidate,
    TextMatch,
    rank_product_catalogue_candidates,
)

MINIMUM_OCR_CONFIDENCE = 0.65


def process_completed_ocr_run(db: Session, image_id: int) -> dict[str, int]:
    """Create missing OCR matches and fused evidence for the latest OCR run.

    The caller owns the transaction. Existing rows are preserved, making the
    operation safe to retry after a worker restart or a partial previous run.
    """
    run = (
        db.query(models.ShelfImageOCRRun)
        .filter(
            models.ShelfImageOCRRun.shelf_image_id == image_id,
            models.ShelfImageOCRRun.status == "COMPLETED",
        )
        .order_by(models.ShelfImageOCRRun.id.desc())
        .first()
    )
    if run is None:
        return {"ocr_matches_created": 0, "fused_evidence_created": 0}

    evidence = (
        db.query(models.ShelfImageOCREvidence)
        .filter(
            models.ShelfImageOCREvidence.run_id == run.id,
            models.ShelfImageOCREvidence.detection_id.is_not(None),
        )
        .order_by(models.ShelfImageOCREvidence.id.asc())
        .all()
    )
    grouped: dict[int, list[models.ShelfImageOCREvidence]] = {}
    for region in evidence:
        grouped.setdefault(region.detection_id, []).append(region)

    existing_matches = {
        row.detection_id: row
        for row in db.query(models.ShelfImageOCRMatch)
        .filter(models.ShelfImageOCRMatch.run_id == run.id)
        .all()
    }
    # The caller must hold the source ShelfImage row lock before entering
    # this pipeline. Lock catalogue rows only afterwards, in ascending ID
    # order, so product deactivation cannot race suggestion/fusion persistence.
    detections = (
        db.query(models.ShelfImageDetection)
        .filter(models.ShelfImageDetection.shelf_image_id == image_id)
        .order_by(models.ShelfImageDetection.id.asc())
        .all()
    )
    referenced_product_ids = {
        detection.product_id for detection in detections
        if detection.product_id is not None
    }
    active_product_ids = {
        product_id for (product_id,) in (
            db.query(models.Product.id)
            .filter(models.Product.is_active.is_(True))
            .all()
        )
    }
    product_ids = sorted(active_product_ids | referenced_product_ids)
    locked_products = (
        db.query(models.Product)
        .filter(models.Product.id.in_(product_ids))
        .order_by(models.Product.id.asc())
        .with_for_update()
        .populate_existing()
        .all()
    )
    active_products = [product for product in locked_products if product.is_active]
    active_product_ids = {product.id for product in active_products}
    catalogue = [
        CatalogueProduct(product.id, product.sku, product.name, product.brand, product.unit)
        for product in active_products
    ]

    matches_created = 0
    for detection_id, regions in grouped.items():
        if detection_id in existing_matches:
            continue
        observed_text = " ".join(
            item.text.strip() for item in regions if item.text.strip()
        )
        confidence = min(item.confidence for item in regions)
        if confidence < MINIMUM_OCR_CONFIDENCE or not observed_text:
            status, suggested_id, top_score, margin, candidates = (
                "UNKNOWN", None, None, None, []
            )
        else:
            match = rank_product_catalogue_candidates(observed_text, catalogue)
            status = match.status
            suggested_id = match.product_id
            top_score = match.score
            margin = match.margin
            candidates = [
                {
                    "product_id": item.product_id,
                    "score": item.score,
                    "reasons": list(item.reasons),
                }
                for item in match.candidates
            ]
        row = models.ShelfImageOCRMatch(
            run_id=run.id,
            detection_id=detection_id,
            suggested_product_id=suggested_id,
            observed_text=observed_text,
            ocr_confidence=confidence,
            status=status,
            top_score=top_score,
            margin=margin,
            candidates=candidates,
        )
        db.add(row)
        existing_matches[detection_id] = row
        matches_created += 1

    db.flush()

    existing_fused = {
        row.detection_id: row
        for row in db.query(models.ShelfImageFusedEvidence)
        .filter(models.ShelfImageFusedEvidence.ocr_run_id == run.id)
        .all()
    }

    fused_created = 0
    for detection in detections:
        if detection.id in existing_fused:
            continue

        visual_status = detection.sku_match_status or "UNKNOWN"
        visual_product_id = (
            detection.product_id
            if visual_status == "MATCHED"
            and detection.product_id in active_product_ids
            else None
        )
        if visual_status == "MATCHED" and visual_product_id is None:
            visual_status = "UNKNOWN"
        visual = ProductMatch(
            status=visual_status,
            product_id=visual_product_id,
            similarity=detection.sku_similarity,
            margin=detection.sku_match_margin,
            candidates=(),
        )

        text_row = existing_matches.get(detection.id)
        if text_row is None:
            text = TextMatch("UNKNOWN", None, None, None, ())
            ocr = None
        else:
            text_candidates = tuple(
                TextCandidate(
                    product_id=int(item["product_id"]),
                    score=float(item["score"]),
                    reasons=tuple(item.get("reasons", [])),
                )
                for item in (text_row.candidates or [])
            )
            text = TextMatch(
                status=text_row.status,
                product_id=text_row.suggested_product_id,
                score=text_row.top_score,
                margin=text_row.margin,
                candidates=text_candidates,
            )
            ocr = (
                OCRText(
                    text=text_row.observed_text,
                    confidence=text_row.ocr_confidence,
                )
                if (text_row.observed_text or "").strip()
                else None
            )
            if ocr is None:
                text = TextMatch("UNKNOWN", None, None, None, ())

        fused = fuse_product_evidence(visual, text, ocr)
        db.add(models.ShelfImageFusedEvidence(
            ocr_run_id=run.id,
            detection_id=detection.id,
            status=fused.status,
            suggested_product_id=fused.suggested_product_id,
            visual_product_id=fused.visual_product_id,
            text_product_id=fused.text_product_id,
            visual_status=visual.status,
            text_status=text.status,
            visual_similarity=visual.similarity,
            text_score=text.score,
            ocr_confidence=fused.ocr_confidence,
            visual_model_version=detection.embedding_model_version or detection.model_version,
            ocr_provider=run.provider,
            ocr_model_version=run.model_version,
            reason=fused.reason,
        ))
        fused_created += 1

    db.flush()
    return {
        "ocr_matches_created": matches_created,
        "fused_evidence_created": fused_created,
    }
