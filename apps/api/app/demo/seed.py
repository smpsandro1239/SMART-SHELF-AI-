"""Idempotent local demo seed: python -m app.demo.seed (from apps/api)."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal
from app.security import hash_password

DEMO_STORE_CODE = "DEMO-BRAGA"
DEMO_USERS = (
    ("admin@demo.smart-shelf.local", "Administrador Demo", "ADMIN", "DemoAdmin2026!"),
    ("supervisor@demo.smart-shelf.local", "Supervisora Demo", "SUPERVISOR", "DemoSupervisor2026!"),
    ("employee@demo.smart-shelf.local", "Funcionário Demo", "EMPLOYEE", "DemoEmployee2026!"),
)
DEMO_PRODUCTS = (
    ("DEMO-001", "Leite meio-gordo 1 L"), ("DEMO-002", "Leite magro 1 L"),
    ("DEMO-003", "Bebida de aveia 1 L"), ("DEMO-004", "Iogurte natural 4x"),
    ("DEMO-005", "Manteiga com sal 250 g"), ("DEMO-006", "Queijo flamengo 200 g"),
    ("DEMO-007", "Sumo de laranja 1 L"), ("DEMO-008", "Água mineral 1,5 L"),
    ("DEMO-009", "Cereais integrais 500 g"), ("DEMO-010", "Café moído 250 g"),
    ("DEMO-011", "Bolachas de aveia 200 g"), ("DEMO-012", "Arroz agulha 1 kg"),
    ("DEMO-013", "Massa esparguete 500 g"), ("DEMO-014", "Azeite virgem 750 ml"),
    ("DEMO-015", "Atum em lata 120 g"),
)


def create_synthetic_shelf_image(destination: Path) -> Path:
    """Create a clearly synthetic, locally generated shelf photograph substitute."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return destination
    image = Image.new("RGB", (1200, 700), "#e9edf0")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1200, 95), fill="#26384a")
    draw.text((38, 32), "SMART SHELF AI  |  SYNTHETIC DEMO SHELF", fill="white", font=ImageFont.load_default())
    palette = ["#e6a23c", "#6aa6d8", "#8bbf91", "#c78ab4", "#d97862", "#9c9ed5"]
    for row, top in enumerate((145, 335, 525)):
        draw.rectangle((35, top + 125, 1165, top + 145), fill="#71808c")
        for slot in range(10):
            x = 58 + slot * 108
            # Deliberate gap in the first row illustrates an empty facing.
            if row == 0 and slot in (4, 5):
                continue
            color = palette[(row * 3 + slot) % len(palette)]
            draw.rounded_rectangle((x, top, x + 76, top + 118), radius=8, fill=color, outline="#425466", width=3)
            draw.rectangle((x + 9, top + 18, x + 67, top + 34), fill="#f8f8f4")
            draw.rectangle((x + 13, top + 51, x + 63, top + 92), fill="#f4f1e9")
    image.save(destination, format="PNG", optimize=True)
    return destination


def _get_or_create_user(db: Session, store_id: int, email: str, name: str, role: str, password: str) -> models.User:
    user = db.query(models.User).filter(models.User.email == email).one_or_none()
    if user is None:
        user = models.User(email=email, full_name=name, role=role, store_id=store_id,
                           password_hash=hash_password(password), is_active=True)
        db.add(user)
    else:
        user.full_name = name
        user.role = role
        user.store_id = store_id
        user.is_active = True
    return user


def seed_demo_data(db: Session, assets_dir: Path | None = None) -> dict:
    """Upsert the deterministic store, users, catalogue and inventory fixtures."""
    store = db.query(models.Store).filter(models.Store.code == DEMO_STORE_CODE).one_or_none()
    if store is None:
        store = models.Store(code=DEMO_STORE_CODE, name="Demo Store Braga")
        db.add(store)
        db.flush()
    else:
        store.name = "Demo Store Braga"

    zone = db.query(models.Zone).filter_by(store_id=store.id, name="Zona de Frescos e Mercearia").one_or_none()
    if zone is None:
        zone = models.Zone(store_id=store.id, name="Zona de Frescos e Mercearia")
        db.add(zone)
        db.flush()

    shelves = []
    for code, description in (("DEMO-A1", "Laticínios e bebidas"), ("DEMO-A2", "Mercearia seca"), ("DEMO-A3", "Conservas e básicos")):
        shelf = db.query(models.Shelf).filter_by(zone_id=zone.id, code=code).one_or_none()
        if shelf is None:
            shelf = models.Shelf(zone_id=zone.id, code=code, description=description)
            db.add(shelf)
            db.flush()
        else:
            shelf.description = description
        shelves.append(shelf)

    products = []
    for sku, name in DEMO_PRODUCTS:
        product = db.query(models.Product).filter_by(sku=sku).one_or_none()
        if product is None:
            product = models.Product(sku=sku, name=name, brand="Marca Demo", unit="un", is_active=True)
            db.add(product)
            db.flush()
        else:
            product.name = name
            product.is_active = True
        products.append(product)

    for index, product in enumerate(products):
        shelf = shelves[index // 5]
        link = db.query(models.ShelfProduct).filter_by(shelf_id=shelf.id, product_id=product.id).one_or_none()
        if link is None:
            db.add(models.ShelfProduct(shelf_id=shelf.id, product_id=product.id,
                                       target_quantity=8, min_display_quantity=2,
                                       position=f"F{index % 5 + 1}"))
        else:
            link.target_quantity = 8
            link.min_display_quantity = 2

        reference = f"DEMO-SEED-{product.sku}-V1"
        snapshot = db.query(models.InventorySnapshot).filter_by(
            store_id=store.id, product_id=product.id, source="MANUAL", external_reference=reference
        ).one_or_none()
        if snapshot is None:
            db.add(models.InventorySnapshot(
                store_id=store.id, product_id=product.id,
                on_hand_quantity=36 if index == 0 else 18,
                reserved_quantity=0, source="MANUAL", external_reference=reference,
                captured_at=models.utc_now(),
            ))

    for email, name, role, password in DEMO_USERS:
        _get_or_create_user(db, store.id, email, name, role, password)

    policy = db.query(models.InventoryFreshnessPolicy).filter_by(store_id=store.id, source="MANUAL").one_or_none()
    if policy is None:
        db.add(models.InventoryFreshnessPolicy(store_id=store.id, source="MANUAL", max_age_minutes=1440))
    else:
        policy.max_age_minutes = 1440

    db.commit()
    asset_root = assets_dir or (Path(__file__).resolve().parents[2] / "demo" / "assets")
    image_path = create_synthetic_shelf_image(asset_root / "synthetic-shelf.png")
    return {
        "store_id": store.id,
        "zone_id": zone.id,
        "shelf_ids": [shelf.id for shelf in shelves],
        "product_ids": [product.id for product in products],
        "employee_id": db.query(models.User.id).filter_by(email=DEMO_USERS[2][0]).scalar(),
        "image_path": str(image_path),
        "users": [{"email": email, "role": role, "password": password} for email, _, role, password in DEMO_USERS],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or refresh the SMART SHELF AI local demo fixtures")
    parser.add_argument("--assets-dir", type=Path, default=None, help="Override the generated synthetic image directory")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        result = seed_demo_data(db, args.assets_dir)
    finally:
        db.close()
    print("SMART SHELF AI demo seed ready")
    print(f"Store ID: {result['store_id']} | Zone ID: {result['zone_id']} | Shelves: {', '.join(map(str, result['shelf_ids']))}")
    print(f"Synthetic image: {result['image_path']}")
    print("Demo accounts (local only):")
    for user in result["users"]:
        print(f"  {user['role']}: {user['email']} / {user['password']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
