# Crema user guide

Open Help in your installation for the chapter buttons and application navigation. This guide describes the current controls and identifies maintainer-assisted steps.

A practical guide from received orders to a completed roast day. Times use **your configured time zone**. Some controls require staff or pay-manager access.

## Daily routine

1. **Check the date and stock.** Use the day you will actually roast. Weigh ready green buckets and available roasted whole beans when counts are uncertain.
2. **Review demand.** Refresh received orders, resolve coffee, size, roast, grind and instructions, and review subscriptions due in the next four days.
3. **Review the plan.** Apply compatible bulk stock, review suggested loads and green-origin decisions, then accept the plan.
4. **Roast on Today.** Prepare the correct Artisan profile. Record Measured, actual finished weight, Roasted and Cooled, and attach logs or photos.
5. **Pack each order.** Follow the customer cards for flavoring, grinding, bagging, labeling and sealing. Mark reserved bulk as actually used when taken.
6. **Finish the day.** Review coverage and remaining work, weigh leftover whole beans, close the completed plan and clock out.

## Set up your roastery

In Administration, add roasters with their actual minimum and maximum green-input weights. Add coffees, kind and standard roast. Blends and flavors keep their standard roast. Flavors need an eligible Medium base; exclude half-caff and decaf from ordinary flavor-base use.

Portal configuration holds the display name, default Medium base, optional four-coffee frac assortment and Shopify Admin bookmark. Give people separate accounts and grant staff access deliberately. Pay-manager access is a separate permission. Choose your marketplaces before creating their connections.

## Orders, plans and batches

**Order**
The finished coffee a customer needs, with roast, bag size, grind and label.

**Plan**
A roasting session's work list, combining compatible demand, bulk contributions and proposed loads.

**Batch**
One physical roaster load with measured green input and an actual finished result.

Several orders can share a compatible batch while keeping their packing instructions. Different coffees, roast levels or custom temperatures stay separate. A removed draft is planning history, not proof that coffee was roasted.

## Import orders

1. Open **Marketplaces & stores**. Choose one platform, several platforms, or manual orders / CSV only.
2. Connect each store once. A store on the earlier Shopify connection should retain that identity.
3. Refresh or upload an orders CSV. Refreshing stages records; it does not create a plan or charge, ship or fulfill orders.
4. Use **Review items** to resolve coffee, size, quantity, roast, grind, instructions and subscription choices. Split portions must still equal the ordered weight.
5. Select ready orders and add them to a plan with the correct roast date.

Whole bean, Regular ground, Fine and Coarse are separate instructions. French press means Coarse. Exclude merchandise explicitly. Custom single-origin roasts require at least 5 lb of that coffee; blends and flavors stay standard. Experimental coffee can use any roast with an origin note.

**Dismiss** hides an order across refreshes until restored. Bulk dismissal acts on the eligible selection. An imported order must first be removed through its plan workflow. Source changes require review and preserve recorded production.

For general CSV imports, choose the owning store and map stable order/line IDs, timezone-aware dates, statuses, title, quantity, bag size and grind. Bag weight is finished coffee per bag, not shipping weight. Preview uploads expire after 30 minutes. WooCommerce, Wix and Squarespace adapters remain experimental until tested against an actual merchant store.

### Find an order that seems missing

Use **Find a Shopify order** on Import orders. It may already belong to a plan, be dismissed, be fulfilled or need item review. Restore a dismissed order explicitly. Recovery does not override payment or delivery holds. Older orders may need a CSV when the connection cannot read them.

## Partial refunds and shipping labels

**Paid and partially refunded orders** can proceed after remaining coffee quantities, instructions and fulfillment pass review. Refunding shipping for local pickup does not mean the coffee was refunded. The original payment status remains visible.

Live Shopify refresh uses current item quantities, excluding refunded or removed units. Check CSV quantities against the store. Cancelled, fully refunded, unpaid, dismissed or partially fulfilled orders do not become ready simply because some payment remains.

A shipping label can mark an order fulfilled before roasting is complete. For an order already on an active plan, use **Confirm still needs production** when offered. Check its existing demand and give a reason. This retains work without creating another order or changing Shopify. Item changes, cancellations and partial deliveries need separate review.

Where practical, buy shipping labels after production and packing. Keep completed orders completed; do not add copies to work around status.

## Subscriptions and early production

Charged renewals arrive as real marketplace orders with stable IDs. The subscription export supplies the upcoming schedule, not a list of paid orders. Access to contracts belonging to another subscription app is not assumed.

### Prepare deliveries due in the next four days

1. Refresh the subscription export when its schedule is old.
2. Open **Review upcoming subscriptions** in the planner. A new empty plan may open this automatically.
3. Choose a delivery and confirm preparation ahead of its charge date.
4. Choose and split each general assortment for this cycle, then add it to its designated plan. Fixed coffees retain their known choices.

Early deliveries are **scheduled**, not paid. No Shopify charge is created. When the real renewal arrives, use **Review early subscription plans**. Compare customer, date, products and quantity; link the matching delivery or confirm it is different. A linked renewal cannot add duplicate roasting or packing.

Pickup exports can omit names. Verify a missing name using the exact contract ID, not a similar date or product. Preserve verified names when an export leaves them blank; if a refresh would erase them, stop and request review.

Known next-14-day subscriptions can optionally fill label-sheet spaces. Those label forecasts do not create production orders.

## Wholesale orders and accounts

1. Select a saved account or enter a one-time customer.
2. Choose a plan and add a row per coffee, bag size and grind.
3. Use 12 oz, 5 lb or 2.5 oz fracs. The wholesale workflow does not offer 16 oz bags.
4. Review finished totals and labels, then save the real order.

**Wholesale accounts** can save customers without placing orders. Preferences stay separate from orders. **Load usual order** supplies a starting point to review. Exclusive coffees are restricted to their account. The optional four-coffee frac assortment requires four configured, different active coffees.

## Plan loads and use stock

Automatic suggestions normally target ordered finished coffee plus the plan's 5% spillage allowance, then apply its loss estimate to calculate green input. Planning estimates do not replace actual measurements.

1. Update measured bulk roasted counts.
2. Review compatible coffee, roast and temperature. Reserved coffee is set aside; record it as used when actually taken.
3. Check the machines, loads, profiles and green-origin decisions. Explicitly skip the stock check if counts are uncertain.
4. Accept the plan to display its roast schedule on Today.

### Machine minimums and small orders

Suggestions respect configured minimums and maximums. Meeting a minimum can produce visible surplus. Bulk covering the target needs no new batch. Normal saves, splits, combinations and preparations check those bounds; an explicit weight override is a separate correction.

### Combine drafts after using Split

Choose **Combine / rebalance drafts**, select at least two compatible unstarted loads and a roaster, then review the preview. It preserves the selected total, other loads and order packing instructions. An accepted plan returns to Draft for review. Recorded production, used stock, started packing and reviewed green-origin requests prevent combining.

**Reset to automatic suggestions** recalculates the whole coffee group. Combine preserves selected weights. Do not use either to manufacture finished output for coffee that was never roasted.

## Read finished-coffee totals

**Ordered**
The customer's finished coffee requirement.

**New roast results**
Actual finished weights recorded for this plan.

**Bulk reserved**
Coffee set aside, not yet recorded as taken.

**Bulk used**
Bulk coffee actually taken and recorded for this plan.

**Total recorded**
New results plus bulk used. Reservations are excluded.

**Still to record**
Ordered coffee not yet covered by recorded output. Review each coffee and roast separately.

For example: 80 oz ordered, 60 oz newly roasted and 20 oz bulk used give 80 oz recorded. If those 20 oz are only reserved, recorded output remains 60 oz.

Output above the order is not automatically leftover stock: packing loss and spillage can use some of it. Weigh actual unallocated whole beans after packing before crediting bulk. Do not count the same excess twice. Deliberate minimum loads or overrides can exceed the usual 5% allowance.

## Record roasting on Today

Today groups accepted loads by machine, then light to dark. Importing and planning remain on their own pages.

1. Weigh green input and mark **Measured**. A configured green recipe deducts it once.
2. Prepare and roast with the correct machine and profile.
3. Mark **Roasted** when appropriate, even before weighing the result.
4. Enter actual finished ounces, normally to one decimal place. Saving a result also marks Roasted.
5. Mark **Cooled** after cooling. A finished weight does not check this automatically.

**Hide cooled** changes the view, not the records. Use **Capture photo** or **Upload .alog** below a batch after it is recorded as roasted. Photos are optional. **Review roast / logs** shows attached logs, their saved references and curve overlays.

### Correct an active green weight

Use **Override weight** on Today or **Override green weight** in planning. Enter ounces, a reason and the confirmation. An explicit per-load exception can exceed configured bounds; automatic suggestions keep normal limits.

The correction preserves acceptance, other loads, results and packing. Previously accounted green usage changes only by the difference using the saved recipe. Green input cannot fall below its recorded finished weight. Get a fresh Artisan preparation after changing a load.

## Green inventory and suppliers

Track the actual origins or lots loaded into the roaster, including separate blend ingredients. Suppliers and green origins are separate from retail products. A green lot does not reactivate a retired retail coffee.

Receive a purchase once. Add cost when known; missing costs remain unknown. Invoice edits and voiding invoice details do not change physical beans. Purchase quantity, current stock and supplier notes describe different facts.

### Bagged / on deck is not ready stock

Delivered sacks can wait before rotation. Preserve their purchase records with **Bagged / on deck** notes and hold these lots out of active inventory and recipe choices. They remain visible in Purchases.

**Current limitation:** on-deck designation and transfers are maintainer-assisted. There is no dedicated on-deck or bucket-transfer button. Provide the supplier reference, lot and intended quantities when requesting the change. A note alone does not disable an active lot.

Bills of lading can show approximate shipping weight including sacks or a pallet. Prefer net bean weights. If estimates are deliberately recorded, label them, retain their source and uncertainty, and distinguish inferred figures from verified weights.

### Bring measured amounts into buckets

1. Identify the exact origin and lot.
2. Weigh beans going into the bucket, excluding the container.
3. Provide that measured amount and date for a transfer into active bucket stock. Remaining sacks stay on deck. Request maintainer assistance while the transfer control is unavailable.
4. Keep the original purchase. This is a transfer, not another receipt or a second credit for the shipment.

**Fresh count** replaces an available balance; it does not add to it. Count beans actually remaining in active storage, excluding input already marked Measured. Reconcile bagged reserve separately. Re-entering a receipt or an old bucket count can overstate stock.

### Recipes and automatic deductions

In **Green recipes**, select the physical coffee or blend and active ingredients totaling 100%. A single origin usually uses one ingredient at 100%. Flavors use their physical Medium base's recipe. An experimental batch may select a direct green origin.

Automatic deduction requires a usable recipe or direct origin before a load is first accounted. Adding a recipe later does not backfill historical measured loads. Existing tracked loads keep their saved ingredient split. Do not guess past usage or subtract it twice.

### Uncertain stock and substitutions

**Skip stock check** records availability as not checked; it does not disable an existing measured deduction. A shortage can request a different green origin, ranked by recorded roast suitability and then flavor tags. Review caffeine and product suitability before approval. Approved plan-specific ingredients apply to remaining unmeasured loads. Changed counts or plans require fresh review.

## Bulk roasted whole beans

Count whole beans before flavoring or grinding. Counts are manual because use outside Crema can change stock. Administration's **bulk_stock_enabled** setting chooses quick-count coffees; the full form also handles occasional compatible single-origin stock.

Reservation and use are separate. Record actual use when taking beans for a plan. If unsure whether earlier usage was already subtracted, obtain a fresh physical count. After packing, weigh leftovers before recording stock; green input, expected yield and planning surplus are not measured finished-stock credits.

## Artisan, Companion and completed logs

Upload your Fahrenheit profiles, preview and approve machines and roast, and set Charge and Drop targets. Derived alarm copies mark Charge, Drop and Off at Drop plus 0.1°F with event guards. Choose First or Second according to the machine's condition and approved profile instructions.

### Install and connect Companion

1. On the roasting computer, open **More → Install Companion** and download an available verified Windows release.
2. Before updating, use **Exit Companion** from the coffee tray icon. X and Hide to tray leave it running.
3. Open **Roasts / connection**, enter the actual portal address, choose **Connect to Crema** and approve its code in the browser.
4. Select an accepted, active, unroasted load and correct profile. Refresh after plan changes.

**Download not available yet** means the installation has no published package. Approved preparation ZIPs remain an alternative. The public demo can show instructions without offering private pilot downloads.

### Prepare and review a roast

Save previous work and keep monitoring off during preparation. The helper can hand the background and alarms to an already open, idle Artisan window. Verify both loaded correctly. A sent request is not proof Artisan accepted it. Companion never starts monitoring, recording or roaster controls.

Preparation titles use coffee name, green ounces to tenths, First=1 or Second=2, and C/C+/FC/FC+/V/F. Background loading does not set the active title: copy it into **Roast → Properties**. Keep date/time or batch counters in autosave filenames to distinguish repeats.

Save the completed foreground .alog, then use **Upload .alog** on the correct Today batch. Preview it, review the preselected reference and attach it. Use **Capture photo** for an optional cooling-bed image. Uploads do not replace measured weights or change stock. **Review roast / logs** provides foreground/reference overlays and original downloads.

## Packing and label sheets

1. Open a collapsible customer card below Today's schedule, or **Bagging / labels**.
2. Check coffee, size, bags, grind and special label. A flavor retains its identity when sharing a Medium base.
3. Complete applicable flavoring, grinding, bagging, labeling and sealing checks.
4. Use **Preview & download label sheets** for the correct plan. Inspect before printing.

Both screens use the same saved records. Reload another open screen to see updates. Administrators can adjust grind and bag counts after clearing the checklist; size × count must still equal ordered coffee.

Match artwork to coffee, size and label identity before marking it ready. Ordinary labels use four positions on US Letter; fracs use eight horizontal positions with artwork rotated. Test on plain paper at 100% / Actual size.

Optional fillers use known next-14-day subscriptions first, then matching-size bags ordered in the last 21 days. Only the final sheet is filled; no additional roast orders are created.

## Close a finished plan

1. Record finished weights and Measured, Roasted and Cooled for every physical roast.
2. Complete each customer's applicable packing checks.
3. Record reserved bulk as used when taken, or resolve unused reservations.
4. Review coffee-specific coverage and source-order issues.
5. Resolve the completion review's issues, then choose **Close completed plan**.

Legacy per-batch Bagged and Sealed fields are not required; customer packing checks are authoritative. Closing preserves a snapshot, links, results and stock use. It does not add leftovers or fulfill marketplace orders. Never invent weights or check unfinished physical steps just to close a plan.

### Correct a completed record

Use **Reopen for corrections** with a reason when production or packing needs correction. Review changed source orders, correct the facts and close again when complete.

For a wrong date or a stale order link with no active demand, request a **maintainer-assisted metadata correction** with the plan, correct date and order number. There is no dedicated metadata-only form. Associated roast dates should be aligned where justified, the original completion time and snapshot preserved, and an audited correction appended without changing physical quantities, packing or stock.

A stale link must not imply that a removed order was produced by the plan. Clearing it does not reverse marketplace fulfillment or make the order ready for duplicate production.

## Tasting notebook

Link notes to a batch or origin sample. House ratings use 0–10; blanks remain unscored. Complete all axes for a radar shape. Scores do not alter yield or stock. Archive mistakes with reasons and retain edit history. Artisan flavor values keep their labelled original scale, separate from portal tastings.

## Costs and margins

Staff can open **More → Coffee & artwork → Costs & margins**. Add a profile for a coffee, roast, label and finished bag size. Keep all costs in one currency. Blank inputs remain unknown; enter 0 only for costs that genuinely do not apply.

1. Enter a reviewed manual green cost per pound, or use the physical coffee's recipe and each ingredient's latest nonvoided landed receipt on or before the basis date. Missing or different-currency costs leave the calculation incomplete. This is an estimate, not FIFO or an accounting stock valuation.
2. Add per-bag packaging, label, flavoring and other production costs. Allocate production minutes and hourly cost; payroll and employee rates are unchanged. Zero minutes explicitly means no allocated labor.
3. Enter retail and wholesale prices before tax and consider discounts. Enter separate retail and wholesale merchant percentages, fixed fees per order and other selling costs. The selected number of identical bags shares one fixed fee; this is not a mixed-order settlement report.
4. Preview with planned yield, or select a completed batch to use its actual yield and saved ingredients. Old green usage is never reconstructed. Estimated receipt weights remain flagged.
5. Save a reviewed estimate to freeze inputs, prices, sources and results. Later profile or invoice edits do not rewrite it. Export saved estimates as CSV.

Production profit subtracts production cost from price. Contribution also subtracts merchant fees and entered other selling costs. Divide profit by price for margin, not markup. Missing production inputs prevent complete production margins; missing fees prevent complete contribution margins. Zero selling prices have no defined percentage margin.

Refresh **Product checks** to read Shopify variant prices, store currency and tax treatment. Explicitly match the exact variant to a cost profile and choose to use its checked retail list price. This never changes Shopify prices or orders. Tax-inclusive or unverified prices need a manual net price. List prices are not discounted order revenue; currencies are not converted.

Labor allocations do not change hours or pay. Cost profiles and snapshots do not change stock or production. Give a reason for assumption edits. These management estimates do not automatically include all overhead or establish accounting/tax treatment.

## Hours and pay

Clock in and out, record breaks, and edit forgotten times or remove incorrect entries with a reason. History remains. Review accumulated unpaid hours, not just a weekly total.

A designated pay manager can set hourly rates and effective dates through PayrollAccess. Employees can view rates and export their own sheets. Payment records identify who paid whom, payment date and hours-through cutoff. Covered hours through that date are marked paid. Enter an amount when known. Pay estimates are straight time before deductions, not payroll-tax calculations.

## Supplies, forecasts and maintenance

Record packaging supplies and flavoring rates to compare demand with bags, sheets and flavoring. Machine maintenance reminders use dates or recorded batch counts. Green forecasts display missing mappings and are estimates, not purchase orders.

External bookmarks open shop administration and shipping tools separately. They do not turn Crema into a shipping or billing system.

## Saving and troubleshooting

### A save failed or another screen looks old

Keep failed values visible and check sign-in and connection. Copy unsaved values before reloading. If another person changed the record, reload and review before retrying. Stale edits are refused to protect their work. A second open screen may need reloading after a successful save.

### A plan is short of finished coffee

Look for an omitted result, reserved bulk not yet used, or a coffee-specific allocation gap. A large overall total does not fill another coffee's shortage. Record facts and add deliberate work only when genuinely needed.

### A label, name or link looks wrong

Identify the exact coffee, size, contract ID, order and plan. Verify against the source before requesting correction. Do not change roast results to work around a catalog or bookkeeping issue.

## Backup and recovery

Use configured HTTPS and separate named accounts. Enter credentials only in protected connection settings. Demonstrations should use fictional data and confined test accounts.

Back up the database with matching instance secret, configuration and private assets. Losing or changing the secret can make saved credentials unreadable. A records export is not a full recovery backup. Keep a tested separate copy and protect private exports.

Test restoration in isolation before replacing a working installation. Preserve later operator work and original keys. Request help if the restored source, database or migration history do not match.
