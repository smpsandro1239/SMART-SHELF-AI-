# PROGRESS

## Latest validated changes

- **2026-11-17 — `8912843`**: production secret tests and validator changes were exercised by API CI run `44148980219` (success); Docker Compose smoke run `44148980184` also passed. The quality-gates run `44148998271` was cancelled by subsequent pushes before jobs started. Vercel checks on the current documentation commit reported the provider build-rate limit, not an application build failure.
- **2026-11-17 — `648762d` / `9de762b`**: production JWT and bootstrap secrets now reject any whitespace character; added parameterized regression tests for whitespace-only and mixed whitespace values. These latest changes still require CI validation.
- Catalogue authorization review: middleware explicitly restricts POST `/products`, `/shelf-products`, `/warehouse/product-profiles` and `/warehouse/product-packaging` to ADMIN; supervisor/employee requests are denied before route execution. Shelf-product listing is scoped to the supervisor's store. No code change made in this pass; targeted regression coverage remains to be assessed.

- **2026-11-17 — `355154e`**: aligned demo detection-to-observation locking with the global image-first lock order and added a regression assertion for the query sequence.
- **2026-11-17 — `08a03a6`**: narrowed the detection-listing row lock to the source `ShelfImage`, avoiding unnecessary locks on joined shelf and zone rows.
- Added root-level `TODO.md` and `PROGRESS.md` to track audit work and evidence-backed validation.
- GitHub Actions for `355154e` completed successfully: API CI, Smart Shelf quality gates and Demo Docker Compose smoke.
- **2026-11-17 — `2840912`**: added regression coverage for observation listing isolation by store and shelf filter; all three workflows passed.

- **2026-11-17 — `6861330`**: added focused settings tests for production JWT/bootstrap secret strength, distinct secrets, and development-only defaults. CI validation is pending.

## Audit notes

- Capture-session tenant isolation, foreign-store create/close denial, employee role restrictions, and upload/session ownership have regression tests in `apps/api/tests/test_auth_middleware_jwt.py`.
- Foreign-store image content, detections, OCR, evidence fusion, retry and human-review access are covered by the authorization test suite.
- No local test execution is claimed; validation above is based on GitHub Actions.

## Current focus

Production configuration review: `Settings` rejects the development JWT key, JWT/bootstrap secrets shorter than 32 characters, known placeholder markers, reused secrets, and (latest, pending CI) any whitespace in either production secret when `APP_ENV=production`. Added tests that isolate inherited CI environment variables. Initial CI exposed environment leakage in two tests; corrected the tests, enforced distinct JWT/bootstrap values, and added rejection coverage for known placeholder/example/test secrets. Revalidation pending; intermediate workflow runs were cancelled by subsequent commits.

Continue reviewing catalogue authorization, derived-image retention races and worker lease/retry behavior. Do not mark an item complete until its relevant automated checks pass.
