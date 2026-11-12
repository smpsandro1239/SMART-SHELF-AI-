"""Offline HTML review gallery for COCO object-detection annotations.

The report references the original image files; it does not copy, modify or upload them.
Run from apps/api:
    python -m app.coco_review --annotations /data/instances_train.json \
        --image-root /data/images/train --output /data/review/index.html
"""
import argparse
import html
import json
import os
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import quote

from app.coco_dataset import validate_coco_document

PALETTE = (
    "#00a6fb", "#f72585", "#ffb703", "#06d6a0",
    "#9b5de5", "#fb8500", "#4cc9f0", "#e63946",
)


def _safe_image_path(image_root: Path, file_name: Any) -> Path:
    """Resolve a COCO image path and reject absolute paths and traversal."""
    if not isinstance(file_name, str) or not file_name.strip() or "\x00" in file_name:
        raise ValueError("image file_name must be a non-empty string")
    relative = Path(file_name)
    windows_path = PureWindowsPath(file_name)
    if relative.is_absolute() or windows_path.is_absolute() or windows_path.drive or "\\" in file_name:
        raise ValueError(f"absolute or non-portable image path is not allowed: {file_name}")
    root = image_root.resolve()
    candidate = (root / relative).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError(f"image path escapes image root: {file_name}")
    if not candidate.is_file():
        raise ValueError(f"image file is missing: {file_name}")
    return candidate


def _annotation_svg(
    image: dict[str, Any],
    annotations: list[dict[str, Any]],
    categories: dict[int, str],
) -> str:
    width, height = image["width"], image["height"]
    parts = [
        f'<svg class="overlay" viewBox="0 0 {width} {height}" '
        'preserveAspectRatio="none" aria-label="Caixas delimitadoras">'
    ]
    for annotation in annotations:
        x, y, box_width, box_height = annotation["bbox"]
        category_id = annotation["category_id"]
        label = categories.get(category_id, f"category {category_id}")
        color = PALETTE[category_id % len(PALETTE)]
        safe_label = html.escape(label, quote=True)
        text_y = max(14, y - 4)
        parts.append(
            f'<rect x="{x:g}" y="{y:g}" width="{box_width:g}" '
            f'height="{box_height:g}" fill="none" stroke="{color}" '
            'stroke-width="2" vector-effect="non-scaling-stroke"/>'
            f'<text x="{x:g}" y="{text_y:g}" fill="{color}" '
            'font-size="14" font-weight="700" '
            'paint-order="stroke" stroke="#111827" stroke-width="3" '
            f'stroke-linejoin="round">{safe_label}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def build_review_html(
    document: Any,
    image_root: Path,
    *,
    class_ids: set[int] | None = None,
    limit: int | None = None,
    include_unannotated: bool = False,
    report_dir: Path | None = None,
) -> tuple[str, dict[str, int]]:
    """Build an offline review page after validating COCO and image paths."""
    errors = validate_coco_document(document)
    if errors:
        raise ValueError("invalid COCO document: " + "; ".join(errors[:10]))
    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
    ):
        raise ValueError("limit must be a positive integer")

    categories = {item["id"]: item["name"] for item in document["categories"]}
    by_image: dict[int, list[dict[str, Any]]] = {
        item["id"]: [] for item in document["images"]
    }
    for annotation in document["annotations"]:
        if class_ids is None or annotation["category_id"] in class_ids:
            by_image[annotation["image_id"]].append(annotation)

    selected = []
    for image in document["images"]:
        annotations = by_image[image["id"]]
        if not annotations and not include_unannotated:
            continue
        selected.append((image, annotations))
    if limit is not None:
        selected = selected[:limit]

    root = image_root.resolve()
    output_dir = (report_dir or Path.cwd()).resolve()
    cards = []
    total_boxes = 0
    for image, annotations in selected:
        actual_path = _safe_image_path(root, image["file_name"])
        relative_to_report = os.path.relpath(actual_path, output_dir)
        image_uri = quote(relative_to_report.replace(os.sep, "/"), safe="/")
        file_label = html.escape(image["file_name"])
        cards.append(
            '<article class="image-card">'
            f'<header><strong>{file_label}</strong>'
            f'<span>{len(annotations)} anotação(ões) · '
            f'{image["width"]} × {image["height"]}</span></header>'
            '<div class="image-stage">'
            f'<img src="{html.escape(image_uri, quote=True)}" '
            f'alt="Imagem {file_label}" loading="lazy"/>'
            f'{_annotation_svg(image, annotations, categories)}'
            '</div></article>'
        )
        total_boxes += len(annotations)

    if not cards:
        cards.append('<p class="empty">Não existem imagens para os filtros selecionados.</p>')
    title = "Revisão visual COCO"
    html_document = f"""<!doctype html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src file:; style-src 'unsafe-inline'">
<title>{title}</title>
<style>
:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
body {{ margin: 0; padding: 1.25rem; background: #111827; color: #f9fafb; }}
h1 {{ margin: 0 0 .4rem; font-size: 1.5rem; }}
.summary {{ color: #cbd5e1; margin: 0 0 1.25rem; }}
.gallery {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,420px),1fr)); gap: 1rem; }}
.image-card {{ min-width: 0; padding: .75rem; border: 1px solid #475569; border-radius: .75rem; background: #1f2937; }}
.image-card header {{ display:flex; justify-content:space-between; gap:.75rem; margin-bottom:.6rem; font-size:.85rem; }}
.image-card header strong {{ overflow-wrap:anywhere; }}
.image-card header span {{ color:#cbd5e1; white-space:nowrap; }}
.image-stage {{ position:relative; width:100%; }}
.image-stage img {{ display:block; width:100%; height:auto; }}
.overlay {{ position:absolute; inset:0; width:100%; height:100%; pointer-events:none; overflow:visible; }}
.empty {{ padding:2rem; color:#cbd5e1; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="summary">{len(selected)} imagem(ns) · {total_boxes} caixa(s) apresentada(s). Relatório local; as imagens originais não foram copiadas nem alteradas.</p>
<main class="gallery">{''.join(cards)}</main>
</body>
</html>
"""
    return html_document, {"images": len(selected), "annotations": total_boxes}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an offline HTML gallery to review COCO bounding boxes"
    )
    parser.add_argument("--annotations", required=True, type=Path, help="COCO JSON annotations")
    parser.add_argument("--image-root", required=True, type=Path, help="Root directory of source images")
    parser.add_argument("--output", required=True, type=Path, help="Output HTML file")
    parser.add_argument("--class-id", type=int, action="append", help="Only show this category ID; repeat to select multiple")
    parser.add_argument("--limit", type=int, help="Maximum number of images, in COCO order")
    parser.add_argument("--include-unannotated", action="store_true", help="Also show images with no matching annotations")
    args = parser.parse_args()

    try:
        document = json.loads(args.annotations.read_text(encoding="utf-8"))
        page, summary = build_review_html(
            document,
            args.image_root,
            class_ids=set(args.class_id) if args.class_id is not None else None,
            limit=args.limit,
            include_unannotated=args.include_unannotated,
            report_dir=args.output.parent,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(page, encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: cannot generate review report: {exc}")
        return 2

    print(f"Review report generated: {args.output}")
    print(f"Images: {summary['images']} | annotations: {summary['annotations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
