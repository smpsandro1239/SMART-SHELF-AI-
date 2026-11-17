# PROGRESS

## Latest validated changes

- **2026-11-17 — `554e9df`**: dashboard UX changes passed Web CI (`44198503068`); frontend TypeScript and production build passed the corresponding quality-gates job (`44198503127`). Full quality-gates run's API test job remained in progress at documentation time. See Current focus for the implementation and the remaining manual accessibility audit.


- **2026-11-17 — `b982ced` / `0926b94`**: PostgreSQL observation creation versus image retention smoke passed API CI (`44194248812`), including the real HTTP request waiting on the source-image lock, returning HTTP 410 after retention commits, and persisting no observation. Frontend/API quality gates (`44194278316`) and Docker Compose smoke (`44194224077`) also passed.

- **2026-11-17 — `a944e82`**: stale-processing recovery now locks eligible `ShelfImage` rows in ascending ID order, matching the global source-image lock order. The SQL-order regression test passed; API CI (`44159933637`), Smart Shelf quality gates (`44159933623`) and Docker Compose smoke (`44159933607`) all succeeded.
- **2026-11-17 — `9de762b`**: production JWT/bootstrap secret validation and its placeholder/whitespace regression tests passed API CI (`44149640352`), Smart Shelf quality gates (`44149698056`) and Docker Compose smoke (`44149640514`). Quality gates included Python compilation, full API tests and frontend TypeScript/production build. PostgreSQL smoke checks and Docker demo readiness/worker profiles also passed.
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

Dashboard UX refinement (2026-11-17): implemented human-readable day/hour/minute durations, consistent `pt-PT` timestamps with explicit `Europe/Lisbon` timezone abbreviations, stronger secondary-text contrast and readable font sizes, status symbols alongside colour, keyboard-accessible clickable KPI/zone/status summaries with task filters, and a tighter single-task card layout. Frontend CI/build validation is pending. Contrast values target WCAG AA; formal conformance still requires automated and manual contrast verification. The first Web CI run (`44197879520`) caught a missing JSX closing brace in the empty-task filter state; corrected in the follow-up commit, with a fresh build required.


Human detection review versus image retention: added `postgres_human_review_retention_smoke.py` and wired it into API CI. The test holds the source-image row lock, sends the real `POST /api/v1/shelf-image-detections/{id}/reviews` request, restricts the image, and asserts HTTP 410 with no persisted `DetectionSkuReview`. Validation is pending; do not mark this race complete until the new API CI step passes.


Production configuration review: `Settings` rejects the development JWT key, JWT/bootstrap secrets shorter than 32 characters, known placeholder markers, reused secrets, and whitespace in either production secret when `APP_ENV=production`. Tests isolate inherited CI environment variables. Initial CI exposed environment leakage in two tests; corrected the tests, enforced distinct JWT/bootstrap values, and added rejection coverage for placeholder/example/test secrets. The final API, quality-gates and Docker workflows passed.

Worker lease audit found and fixed a race: a worker that loses its processing lease can no longer mark the replacement worker's job FAILED when its own provider call raises. The failure handler now locks and refreshes the image row and changes state only if status and claim timestamp still match. The lease-takeover regression test and the API, quality-gates and Docker Compose workflows passed for 71b3425. Continue reviewing catalogue authorization, derived-image retention races and worker retry behavior; do not mark an item complete until relevant automated checks pass.


### Catalogue write authorization — 2026-11-17

Added `test_catalogue_and_warehouse_master_data_writes_are_admin_only` to exercise all four middleware-protected creation routes as both SUPERVISOR and EMPLOYEE. The test uses empty payloads deliberately: HTTP 403 must be returned by the authorization boundary before request-schema validation or route-side effects. This establishes role-gate coverage only; ADMIN ownership validation, store scoping and concurrent shelf-product reassignment remain open. Commit: `df1030a860d517f2cf519b01672218b3b4d82852`. CI validation is pending; no local test execution is claimed.
