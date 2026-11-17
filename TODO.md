# TODO

## Security and reliability

- [ ] Audit authorization and tenant isolation for computer-vision endpoints: capture sessions, uploads, image content, detections, OCR, evidence fusion, human reviews and embeddings.
- [ ] Add PostgreSQL concurrency coverage for image retention versus detection review. Observation creation versus image retention and human review versus image retention now have dedicated smoke tests; validate the new human-review test in CI.
- [ ] Audit product and shelf-product catalogue writes for role-based access, tenant ownership and concurrent assignment changes.
- [ ] Complete the worker retry, lease-expiry and retention-transition audit under concurrent execution. The lease-takeover and deterministic recovery-lock ordering regression tests now pass CI; add PostgreSQL coverage for any remaining race conditions found.
- [ ] Verify production authentication configuration rejects anonymous access to all protected API routes.
- [ ] Confirm production secret validation (including whitespace rejection) passes in CI and deployment environments explicitly set `APP_ENV=production`.
- [ ] Document the production secret generation, storage and rotation procedure.
- [ ] Review rotation and operational lifecycle for JWT and bootstrap secrets.
- [ ] Re-run API, frontend, Docker Compose and PostgreSQL smoke suites after backend changes.

## Product quality

- [ ] Review pagination, filtering and bounded query costs on image-derived data endpoints.
- [ ] Verify retention and legal-hold audit trails across restore, purge scheduling and cancellation.
- [ ] Keep ROADMAP.md aligned with implemented and validated capabilities.
- [x] Implement dashboard UX refinements: human-readable durations, Europe/Lisbon timestamps, stronger contrast palette, non-colour status cues, compact single-task layout and clickable summary cards with exact task-state filters; Web CI and frontend quality build passed.
- [ ] Complete manual browser/keyboard and full-state contrast audit before claiming formal WCAG AA conformance.
