# Crema roadmap: review candidate to 1.x

Planning baseline: October 30, 2026. Current source candidate: **0.1.0-rc9**, prepared for private recovery/distribution review; operational deployments may remain on an earlier verified candidate. This is a proposed sequence with completion criteria, not a list of delivered features or promised release dates. The current front page remains the accepted roast sheet; a kanban redesign is outside this roadmap.

## What 1.0 means

An independent roastery can install Crema, configure its own catalog and machines, bring in real orders, plan against stock, record production, pack and label those orders, and recover its records without developer intervention. The normal workflow is documented and repeatable. Optional integrations and inventory counts have clear limitations and escape routes.

The stable core remains available under MIT. Managed hosting is optional and has additional readiness gates; a software release does not automatically launch a hosted service. One installation and database per roastery remains the supported architecture.

## Starting point

The candidate already contains order imports and duplicate protection, subscription assortments, wholesale entry, stock-first planning, fixed accepted loads, recorded-versus-reserved coverage, roast results, packing/grinds, supplied artwork, Artisan preparation/logs, optional photos, hours/payments, supplies, maintenance and forecasts. Green recipes, movements, supplier receipts, manual bulk counts and reviewed green-origin substitutions also exist.

These need validation and refinement, not replacement. Full packaged inventory, end-to-end lot tracing, full costing, deadline-aware scheduling, granular roles and MFA are additional work. New marketplace adapters have synthetic coverage; that does not establish live merchant-account compatibility.

## Proposed release sequence

| Version | Main outcome | Required evidence before moving on |
|---|---|---|
| **0.2.0 — Verified public beta** | Distribute the existing core safely. Close operational findings, complete publication/privacy/license review and security review, publish generic versioned images and installation instructions. | Real production cycle, completed Artisan log and operator alarm checks; clean install from the intended image with TLS; restored-data upgrade and recovery; final source/image scan and notices; authorized publication review; small external roastery pilot. No customer assets or private installation migrations in the release. |
| **0.3.0 — Easier daily work** | Improve the existing roast sheet, planning and packing screens without changing the production model. | Operators can follow a complete shift without assistance. Weights, bulk reserved/used, remaining demand and save failures are clear. No duplicated work, lost edits or surprise replanning. |
| **0.4.0 — Inventory and traceability** | Extend existing green/bulk tracking into identifiable lots and packaged finished stock, with deliberate corrections. | Receipt → measured ingredients → actual roast → packing → order trace can be demonstrated; reservations, use, reversals, counts and substitutions reconcile. Unknown historical links stay unknown. |
| **0.5.0 — Costs and deadlines** | Show useful production costs and due-date priorities with uncertainty visible. | Known ingredient, packaging and labor costs reconcile to fixtures; missing costs never become zero-cost profit. Scheduling flags capacity/deadline conflicts and never changes accepted work silently. |
| **0.6.0 — Verified connections** | Make supported import paths dependable and publish a tested compatibility matrix. | Live authorized checks for every adapter called supported, plus retry/deduplication, cancellation/refund handling and permissions tests. CSV/manual operation remains first-class; unverified adapters remain experimental. |
| **0.7.0 — Access and operation** | Define operational roles, add MFA and make upgrades/support safer. | Permission tests for every sensitive read/write/export, recovery flows, audited privileged access and rehearsed key rotation/backup restoration. Payroll access remains separate. Hosted-pilot controls are checked independently. |
| **0.8.0 — Feature freeze and pilot** | Stop expanding the 1.0 scope and resolve practical friction across independent installations. | At least two independent roasteries complete two production cycles each; review failures, time-consuming steps, realistic data volume and repeatable support instructions. Include a manual/CSV workflow. |
| **0.9.0-rc.N — Release candidates** | Exercise the exact release artifact, upgrade path and documentation. | Fresh install, previous-supported-version upgrade, backup restore, export, security/privacy checks and regression suite pass for the same candidate image digest. A material fix produces a new candidate and repeats affected checks. |
| **1.0.0 — Stable core** | Commit to a documented, supported production workflow and compatibility policy. | All 1.0 criteria below pass; known limitations are published; no unresolved release-blocking data-loss, authorization or production-correctness defect. |

Work may overlap, but verification cannot be skipped. A security fix ships when needed rather than waiting for the security milestone. Do not use an untested integration as a prerequisite for the reliable core. If a proposed feature cannot meet the freeze, explicitly move it to 1.1+ and publish the reduced 1.0 scope before releasing.

### 0.2: close the current release gates

1. Complete the real operator production trial and resolve its findings. File loading and synthetic tests do not prove physical alarm behavior.
2. Review code/assets publication authority, reachable source history, final archives, dependency notices and applicable distribution obligations. Review the complete image, not only Python package metadata.
3. Obtain the independent security review described in [SECURITY.md](SECURITY.md), with findings tracked privately until disclosure is appropriate.
4. Build a generic image with a version and recorded digest. Test its intended registry pull, initial setup, domain/TLS, persistent keys, restart and backup path. Never distribute a private customer's image.
5. Rehearse upgrades against a restored operational copy. Preserve keys, history and installation-specific migration chains; prove recovery before promotion.
6. Verify the public documentation and a small external pilot, then review the exact repository/image visibility change. Publishing Crema is not permission to publish unrelated projects.

### 0.3: refine the sheet, keep the workflow familiar

* Keep accepted loads grouped by configured machine order and light-to-dark roast order. For the existing two-machine workflow, preserve largest-capacity machine first.
* Keep finished weight and status controls prominent, with tenths precision, touch/keyboard access and a usable printed sheet.
* Make **reserved bulk**, **bulk actually used**, **newly roasted output**, **recorded finished total** and **remaining to record** unmistakable. Displaying a reservation must never fabricate finished output.
* Keep planning/import controls on their own pages. Small context links/buttons may reveal source orders, packing instructions and Artisan files without filling the production sheet with setup controls.
* Preserve manual Roasted before entering a result; a valid result marks Measured/Roasted. Unknown result weight remains visibly missing, not estimated actual output.
* Preserve stale-edit protection, visible save confirmation, retry and audited undo. Test two users/tabs, expired sessions, timeouts and uncertain saves. A timeout must not silently reapply an inventory movement.
* Keep recorded production fixed when plans change. Show shortages for an explicit decision; never create tiny corrective roasts automatically.

### 0.4: add inventory depth without inventing history

* Extend existing green items/receipts into stable lot identifiers and ingredient snapshots. A manual count is a new observation with an actor/time/reason, not an erased movement ledger.
* Track packaged units separately from bulk whole beans, including coffee, roast, bag size, label and grind. Decide and document the point of deduction/reservation before implementing it.
* Provide a trace view from order to recorded pack/roast/ingredient lot where evidence exists, and a reverse lookup from a lot to affected production/orders. Preserve historical unknowns explicitly.
* Demonstrate partial packs, stock-only orders, count corrections, removed batches, merged inputs, cancelled orders and substitution cancellation without double subtraction.
* Keep the green availability check optional. Skipping availability does not bypass maximum safe machine capacity or change ingredient-deduction semantics.

### 0.5: costs and due dates

* Start with recorded receipt costs and packaging/flavoring costs, then optional labor and configured overhead. Separate historical actual cost from today's replacement-cost estimate.
* Show the portion of the calculation with missing inputs; do not claim a full margin when revenue/cost data is incomplete. Tax, accounting and statutory payroll compliance are outside the first costing release.
* Add due dates/cutoffs and explicit planned production duration. Existing custom-order due dates are a starting point, not a complete scheduling system.
* Suggest feasible work around machine availability and operator input; require review to alter an accepted plan. Forecasts and subscription outlooks remain separate from received production orders.

### 0.6: integrate selectively

* Start with the established Shopify path and mapped CSV. Verify order discovery, pagination, reauthorization, changed orders, duplicate exports, dismissals, refunds/cancellations and renewal order identity.
* Verify WooCommerce, Wix and Squarespace one at a time with authorized test stores/pilot merchants. Do not claim all platforms supported because parsers pass fixtures. Lack of a test merchant leaves that adapter experimental; it need not block stable manual/verified paths.
* Keep marketplace selection explicit and allow multiple choices. Do not require a cloud store for production use.
* Keep Artisan file handoff and completed-log import as the first supported roast-software workflow. Test additional software through representative exports/API permission trials before adding it to the supported list. Preserve original files, units, probe identity and provenance.
* External shipping/admin bookmarks remain bookmarks unless a separate direct integration is chosen. Automatic roaster control is outside 1.0.

### 0.7: protect operating access

* Replace broad staff access where appropriate with documented owner/admin, production, packing and read-only capabilities. Keep payroll/rate authority separately granted. Final role names may change after the permission review.
* Add and test MFA, recovery codes, lost-device recovery and administrator reset auditing. Do not invent an unaudited support bypass.
* Test sensitive exports, artwork/log uploads, store credentials, backup download and rate changes against the role matrix. UI hiding alone is not authorization.
* Publish supported deployment/runtime versions, backup retention/restore procedures, update instructions and security reporting arrangements.
* For paid hosting, separately prove instance isolation, support access, per-customer restore/export/deletion, quotas, monitoring, onboarding/billing and service/privacy terms. Those are service-launch gates, not features every self-hoster must purchase.

## 1.0 acceptance checklist

### Daily production

- [ ] A new roastery can set up catalog, capacities and users from the documentation without maintainer database edits.
- [ ] Manual, CSV and each declared supported live import path preserve order identity and avoid duplicate demand; subscription renewals use actual received orders.
- [ ] Standard/custom/experimental roast rules, flavor bases, grind/label rules and machine capacities hold across entry, import, planning and correction.
- [ ] Partial bulk use and stock-only fulfillment reconcile with new roast output, packing and order completion. No reservation is counted as actual output.
- [ ] Shortfalls and missing measurements invite explicit correction; no unrequested replanning or fabricated completion.
- [ ] Actual weights, status, corrections, ingredient movements and uploaded originals retain an audit trail.
- [ ] Roast sheet, packing and labels work on the declared desktop/mobile/print targets, with keyboard access and understandable save/error states.

### Operation and distribution

- [ ] Generic image/YAML clean install, TLS, unique persistent keys, restart, supported-version upgrade and recovery pass against the release artifact.
- [ ] Users can export usable records and restore a verified backup with documented ownership of keys and files.
- [ ] Privacy/publication/license checks and independent security review are complete; no unresolved release-blocking security issue.
- [ ] Permission/MFA/recovery checks pass, and at least two independent roastery pilots have completed the stated cycles.
- [ ] CI passes SQLite/PostgreSQL, important production/inventory regressions, dependency review, privacy checks and image build. Browser and realistic-volume checks supplement the suite.
- [ ] Installation, help/how-to, troubleshooting, data correction, security and compatibility documentation match shipped behavior.
- [ ] Release notes state supported environments, known limitations and experimental integrations. An exact version/image digest identifies the supported artifact.

Release blockers include unexplained data changes, duplicate demand or stock deductions, unsafe capacity acceptance, lost edits, wrong coffee/grind/label mapping, authorization failures and an unrecoverable supported deployment. A polished appearance cannot compensate for them.

## Version policy after 1.0

* **1.0.x:** focused defect/security fixes, release notes and affected regressions. Do not slip workflow redesigns into patches. State any required migration or operator action.
* **1.x.0:** additive capabilities with documented upgrade and compatibility expectations. Deprecations are announced before removal; review migration impact even when the UI looks unchanged.
* **2.0.0:** intentionally breaking changes to a supported contract or deployment model, with a migration plan. A major number does not excuse data loss.
* Publish a supported-version matrix and security-update policy before 1.0. Do not promise indefinite support for every old minor version. Image rollback alone is not a database downgrade strategy.

## After 1.0: proposed 1.x themes

| Theme | Candidate work | Entry condition |
|---|---|---|
| **1.1 — Better operating insight** | Cost/yield confidence, machine/load comparisons, forecast accuracy and reorder suggestions | Enough trustworthy production history; show sample sizes and uncertainty. |
| **1.2 — Broader interoperability** | Additional verified marketplaces and roast-software imports/APIs | Real authorized pilots or representative exports, maintenance capacity and a documented compatibility matrix. |
| **1.3 — Customer/wholesale convenience** | Customer reorder requests, saved preferences and scan-assisted packing | Authentication/authorization, duplicate-demand protection and privacy review for the new surface. |

These are themes, not a promise to wait until a particular version for a small useful fix. Customer self-service, advanced scanning, automatic camera analysis, shared-database tenancy and remote machine operation are not required for 1.0. No autonomous heating/roaster control is proposed.

## How work moves through the roadmap

For each deliverable: define the operator outcome and acceptance examples → implement in canonical Crema → test with fictional fixtures → run appropriate database/browser checks → rehearse restored-data upgrade/recovery → promote to the private operational pilot → review the actual cycle → release the generic artifact. Keep private data, assets, keys and compatibility migrations out of the product repository.

Use a small active queue: one release-blocking issue and one next milestone at a time. Assign an issue to every acceptance criterion when that milestone starts, with a reproduction/example, owner and evidence link. Reassess the next milestone after each pilot rather than expanding 1.0 continually.

The immediate priority is **0.2 readiness**, including the operator trial and remaining publication/security/image checks. Do not deploy speculative redesigns during that trial. The first planned product improvement after it is **0.3 roast-sheet usability**, with no kanban.
