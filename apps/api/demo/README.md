# Synthetic demo assets

Run `python -m app.demo.seed` from `apps/api` after applying migrations. The seed creates `demo/assets/synthetic-shelf.png` locally using Pillow. The image is generated from geometric shapes and contains no people, customer data, retailer branding, or third-party photography. It is intentionally not committed as a binary; every environment can regenerate it deterministically.
