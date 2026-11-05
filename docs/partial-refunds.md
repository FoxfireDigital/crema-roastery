# Partial refunds and remaining production

A shipping refund for local pickup does not remove ordered coffee. Crema accepts `paid` and `partially_refunded` as production payment states, while retaining the original marketplace status. The import list displays a reminder to check remaining coffee quantities.

All ordinary guards still apply: cancelled, fully refunded, unpaid, dismissed, changed-source or partially fulfilled orders do not become ready merely because a refund exists. Fulfilled orders already assigned to active plans still require explicit remaining-production confirmation. Closed/historical work remains on its original plan and cannot be imported a second time.

Live Shopify normalization uses `currentQuantity`, which excludes refunded and removed units. Unchanged item quantities remain unchanged when only the financial status becomes partially refunded. Changes to item identities, quantities or instructions retain the existing review hold and preserve actual roast/packing records. CSV users must verify remaining quantities against the store because an exported quantity may describe the original purchase. Crema never issues a refund, changes payment status, or marks a Shopify order fulfilled.

Paid or partially refunded real subscription renewals can be explicitly linked to their reviewed early delivery; future scheduled deliveries retain the existing separate forecast handling. Completion uses the same payment eligibility policy.

This correction changes application logic and guidance only. No schema migration or automatic order reassignment is required. Roll back the application image/source while retaining the current database and existing private migration history if needed.
