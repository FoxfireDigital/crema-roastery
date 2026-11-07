# Costs and margins

Staff open **More → Coffee & artwork → Costs & margins**. This is a management estimating tool. It does not revalue inventory, change employee pay, update marketplace prices, charge a customer or establish accounting/tax treatment.

## A profile per product and bag size

Create a named profile for a coffee, roast, packaging-label identity and finished bag weight. Set one currency. Review these assumptions:

- Expected finished yield as a percentage of green input.
- Manual green cost per pound, or receipt costs from the physical coffee's green recipe.
- Packaging, label, flavoring and other production cost per finished bag.
- Allocated production minutes per bag and a labor cost per hour. These are costing assumptions, separate from recorded employee shifts/rates. Explicit zero minutes means no labor allocation.
- Retail and wholesale selling prices, excluding tax and with discounts considered.
- Separate retail and wholesale merchant fee percentages, fixed fees per order and other selling costs per bag, such as a net shipping subsidy.

**Blank means unknown.** Enter `0` only where a cost genuinely does not apply. Missing production components prevent a complete production cost/profit/margin. Missing selling inputs prevent contribution results while retaining available production results. A zero selling price has no defined percentage margin. Amounts in different currencies are never silently added or converted.

## Cost basis

For planned estimates, recipe percentages weight each ingredient's latest nonvoided landed receipt on or before today. The latest receipt's missing price or wrong currency does not silently fall back to an older priced receipt. No usable recipe means a reviewed manual green price is needed. A flavor uses its physical roast base's recipe; its flavoring and packaging costs stay separate.

For an actual-batch estimate, select a compatible completed roast. Its actual green and finished weights determine yield. Saved ingredient amounts supply the physical source split, including an already-recorded substitution. A directly recorded green origin can also be used. Without saved origins, old usage is not guessed from today's recipe. Receipt dates are bounded by the roast date. All costs are still reviewed estimates based on current invoice records, not a reconstruction of historical accounting values. Estimated receipt quantities remain flagged.

This is an explicitly documented **latest-receipt estimating method**, not FIFO, weighted-average inventory valuation or an accounting COGS ledger. It never consumes or releases stock. Inactive/on-deck lots are not activated by a cost estimate. Manual quotes are assumptions, not receipts.

## Arithmetic

`coffee cost per bag = green cost per lb × bag oz ÷ 16 ÷ yield fraction`

`production cost = coffee + bag + label + flavoring + allocated labor + other production`

`labor = minutes per bag × hourly allocation rate ÷ 60`

`production profit = selling price − production cost`

`contribution = production profit − percentage fee − fixed fee / comparison quantity − other selling cost per bag`

`margin % = profit / selling price × 100`

The quantity compares an order of that many identical bags. One fixed merchant fee is spread across that order; it is not charged once per bag. This is not an actual mixed-order or marketplace-settlement profit report. Overall comparison amounts are calculated before rounding individual displayed bag results. Production margin, contribution margin and markup are distinct.

For an independently checkable example: $4/lb green, 80% yield and a 16 oz bag give $5 coffee cost. Add $0.40 packaging, $0.10 label and two minutes at $15/hour: $6 production cost. At $10 retail, production profit is $4 (40%). A 3% fee and $0.30 fixed fee leave $3.40 contribution (34%) for a one-bag order, assuming other selling costs explicitly equal zero. Three identical bags share one fixed fee and contribute $10.80 in total.

## Shopify catalog prices

Refresh **Product checks** using the existing `read_products` connection. Catalog queries now read `ProductVariant.price`, `Shop.currencyCode` and `Shop.taxesIncluded`:

- [ProductVariant price documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/ProductVariant#field-ProductVariant.fields.price)
- [Shop currency and tax documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/Shop)

Select the exact variant on a cost profile and explicitly choose to use it for retail. Review coffee, bag size and grind. Price links remain tied to the checked store/variant/currency, with the check time visible. Changed stores, missing prices, currency mismatches and tax-inclusive/unverified tax treatment leave the linked retail price unavailable; enter a reviewed manual net price instead. These catalog list prices are not discounted customer revenue, shipping income, tax proceeds or settlement amounts. Wholesale price assumptions are separate.

No additional write scopes or Shopify price mutations are used. Failed or malformed catalog responses preserve the previous successful snapshot. A normal catalog refresh never rewrites cost profiles, saved estimates, orders or roast plans.

## Saved estimates and exports

Preview and choose **Save reviewed estimate**. The snapshot retains product identity, quantities, input assumptions, actual-batch weights if selected, receipt IDs/versions/costs, price source/check time, missing inputs and results. A signed review token detects intervening source changes. Duplicate identical submissions return the original saved estimate. Changed payloads, expired forms, wrong users or stale versions are rejected.

Snapshots are append-only through the supported controls and model; later profile/invoice/catalog changes do not rewrite them. Export a dated snapshot as CSV, with formula-safe user-supplied text. Use a new snapshot to compare a correction. Staff access and CSRF protection apply; Companion device credentials provide no access to costing.

The shared demo may contain explicitly fictional profiles, with amounts labeled illustrative. Real installation profiles and prices are private and are never seeded from demo data. Paid hosting, public source and public Companion distribution remain subject to their existing release gates.
