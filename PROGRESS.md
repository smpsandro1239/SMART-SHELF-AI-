# PROGRESS

## Latest validated changes

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

Production configuration review: `Settings` rejects the development JWT key and JWT/bootstrap secrets shorter than 32 characters when `APP_ENV=production`; it now also rejects reuse of the same secret for both purposes. Added tests that isolate inherited CI environment variables. Initial CI exposed environment leakage in two tests; corrected the tests, enforced distinct JWT/bootstrap values, and added rejection coverage for known placeholder/example/test secrets. Revalidation pending; intermediate workflow runs were cancelled by subsequent commits.

Continue reviewing catalogue authorization, derived-image retention races and worker lease/retry behavior. Do not mark an item complete until its relevant automated checks pass.
