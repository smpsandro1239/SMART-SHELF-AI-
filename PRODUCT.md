# SMART SHELF AI — Product context

## Product
SMART SHELF AI is an operational platform for retail teams. It brings together shelf-image capture, computer-vision evidence, inventory context, replenishment recommendations, human review, task execution, and auditable inventory reconciliation.

## Primary users
- **ADMIN:** configures and administers the platform and has cross-store responsibilities where authorized.
- **SUPERVISOR:** reviews operational evidence, approves replenishment, assigns work, and monitors a store.
- **EMPLOYEE:** executes assigned shelf-replenishment tasks and records completion or exceptions.

The API is the authority for permissions and business rules. The frontend must not infer access from hidden controls alone.

## Core user outcomes
1. Understand what needs attention in a store and why.
2. Review shelf evidence without confusing uncertainty with an empty shelf.
3. Approve, assign, execute, and reconcile replenishment with explicit human decisions.
4. Trace changes to their actor, evidence, timestamp, and source.
5. Capture images and inspect analysis status, detections, and review history.

## Product truth and constraints
- The local demo uses deterministic mock vision and synthetic data.
- No production-ready trained vision model, live CCTV/VMS integration, or operational POS/ERP/WMS integration is claimed.
- Vision observations do not directly mutate stock.
- `UNKNOWN`, unavailable camera/image evidence, and analysis failures must not be presented as `OUT_OF_STOCK`.
- Human review and approval remain explicit for SKU identity, shelf status, replenishment, and inventory reconciliation.
- Multi-tenant isolation and role authorization are enforced by the API; UI affordances must reflect but never replace those checks.
- Privacy, retention, legal hold, lineage, and auditability are product requirements.

## Surface mode
The existing web application is an internal operational product interface: **Operate** mode. Optimize for fast comprehension, reliable task completion, information density, predictable navigation, and accessible controls. Avoid marketing-page patterns.

## Language and content
The primary product language is Portuguese (Portugal). Use concise, action-oriented labels and explicit status wording. Technical identifiers may remain in English where they are part of API contracts or established domain vocabulary.

## Design constraints
Preserve the current product identity unless a redesign is explicitly requested. Do not invent commercial claims, AI accuracy metrics, real-time camera coverage, stock figures, or integration status. Label synthetic/demo information clearly.
