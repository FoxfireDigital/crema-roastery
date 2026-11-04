# Roast-day corrections and wholesale accounts

## Correct one green load

On Today, choose **Override weight** below the load's green ounces. The planner also offers **Override green weight** for each load, including started batches. Enter the actual/intended weight in tenths, a reason and the confirmation. This explicit per-load correction may exceed that machine's configured minimum or maximum; ordinary automatic suggestions retain those limits. For example, a confirmed 144.0 oz correction does not change a machine's normal 140.0 oz maximum.

The change keeps the plan's acceptance, existing finished weight, cooling, photos, logs, packing and other batches. It marks that coffee group's drafts as manually sized, preventing automatic recalculation from replacing the correction. Green input cannot be below an existing finished weight. Already-accounted measured green usage changes only by the difference, using the original saved recipe. Untracked historical green stock is not backfilled.

A stale page is rejected. Earlier Artisan preparations become stale after a changed weight/version: obtain a fresh preparation for an unroasted load. Removed, merged, closed and historical work must be reviewed through their existing correction workflows.

## Review subscriptions for the next four days

New empty plans open the subscription review when known active deliveries fall within the next four days. The planner always has **Review upcoming subscriptions**. Dates and fixed items come from the latest subscription export; refresh it when outdated. No dates are extrapolated from old contracts. Subscription CSV variants are resolved from the saved product check and previously known contract details; a private mapping file is optional. Refresh Check products before importing newly added variants. Unknown variants stop the import with an actionable message and preserve the previous subscriptions.

Choose a delivery and confirm preparation ahead of its charge date. Crema stages it as **scheduled**, not paid. No Shopify order, charge or payment is created. Each assortment starts without a coffee selection; choose and split that delivery's coffees using the ordinary item review. Then add the reviewed delivery to its designated plan. The contract and due date identify a single early delivery, so retries do not create another one.

When real recurring orders arrive while early deliveries remain unmatched, review them against that work. Open **Review early subscription plans** from item review. Choose the existing early delivery after comparing customer, dates, coffee choices and quantities, or confirm **Different delivery — import normally**. Matching only a name or weight is insufficient; no automatic identity matching occurs. A linked renewal is excluded from new production demand. Existing loads, packing and stock usage are retained. Later refund, cancellation or source-item changes require review. Closed snapshots are retained, with subsequent linkage recorded in the plan's audit history.

Pending unmatched deliveries may include completed work; resolve them as their actual renewals arrive. An early delivery already included in a plan is excluded from the separate advance-label filler, avoiding another set of forecast labels.

## Wholesale accounts and exclusive coffees

Use **Wholesale accounts** from Add wholesale order to save a business name, usual grind and optional notes before knowing its usual coffee order. Creating an account creates no production demand. Existing usual-order preferences remain available separately.

Choose the account at the top of the order form. Switching accounts updates its identity and product availability without reloading unsaved rows. Use **Load usual order** deliberately when you want saved coffee quantities; otherwise enter new rows. Supported wholesale formats remain 5 lb, 12 oz and 2.5 oz frac bags/four-coffee assortments.

In Coffee administration, **Wholesale only customer** restricts an exclusive coffee to one saved account. Other wholesale accounts and ordinary retail/manual-order entry cannot select it. Backend validation enforces the same rule. Deactivating an account removes it from new account choices while preserving existing orders and preferences.

## Close a completed plan

Each physical roast needs its actual finished weight and Measured, Roasted and Cooled. Each customer's applicable grinding, flavoring, bagging, labeling and sealing steps belong on the shared packing checklist. Legacy per-batch Bagged/Sealed values no longer block closure. Coffee coverage, bulk actually used and source-order checks still apply. Existing closure snapshots are not rewritten by this update.
