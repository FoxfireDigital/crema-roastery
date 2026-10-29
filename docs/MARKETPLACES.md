# Connected stores and order imports

Open Import orders → Connected stores. A refresh stages source orders for review; only selected, eligible orders become production demand. Connections are independent: identical order numbers in different stores do not collide, and saved product mappings belong to their store.

## Current support and verification

The new adapters cover Shopify, WooCommerce, Wix and Squarespace. Synthetic adapter, pagination, permissions, retry and changed-order checks pass locally. Merchant-account verification for the new adapters remains pending. Treat those adapters as experimental until a real authorized test on that platform has passed. The existing Shopify authorization, product checks and webhook path remain separate and available.

These adapters poll read endpoints. They do not install marketplace apps, take payments, create shipments, mark fulfillment or modify subscription contracts. A platform may require a paid plan or approved permissions to supply its API; Crema does not bypass those requirements. Other marketplaces can use the general CSV importer with explicit column mapping.

## Connection setup

* WooCommerce: provide the public HTTPS store address, including any WordPress subdirectory, and a consumer key and secret with **Read** permission for orders. Put credentials in the form, not the URL.
* Shopify: provide the merchant's `myshopify.com` address and an authorized Admin API token with `read_orders`. Use the existing Shopify screen for a store already connected there. Do not add a second connection for it; earlier order identities must remain intact. Product checks and subscription outlook currently use the existing Shopify workflow.
* Wix: provide the exact site ID and an authorized API key or access token with **Read Orders**. The request uses Wix's fixed API host and the site header.
* Squarespace: provide the merchant website address to identify the store and an API key with **Orders: Read Only**. Requests use Squarespace's fixed Commerce API host.

Customer names are optional and disabled by default. Enable them only when permitted by the merchant account and needed for the workflow. Shipping addresses and payment credentials are not needed for roasting and are not imported by these adapters.

Saved credentials are encrypted with the instance secret. Edit forms never show them again. Blank credential fields retain the existing value. Keep the secret with the protected database backup; changing it breaks decryption. Pause a connection to stop future checks. Rotating credentials does not create a new store identity.

## Refresh and review

Press Refresh orders to verify access. Automatic refresh is opt-in and checked about every five minutes by the background worker. Initial API windows cover the last 59 days. Later windows overlap the last completed watermark by ten minutes. A refresh processes up to five pages; Continue refresh resumes its saved position. Failure preserves completed pages and the saved position rather than declaring the whole window complete. Old source timestamps cannot rewind newer facts.

Unknown payment state, unpaid/refunded orders, cancellations, partial fulfillment, unsupported delivery states and test/POS flags are held for review. Only clearly paid, unfulfilled deliveries can enter normal production. Custom grind, bag size or roast details that cannot be inferred stay unresolved; shipping weight is never treated as net coffee weight.

Identical refreshes retain deliberate assortments, grind choices and dismissals. Changed source items are shown for review. An affected accepted plan goes back into review while actual roast results remain intact. Dismissal remains saved across refreshes until explicitly restored.

Actual charged subscription renewal orders can be imported. Upcoming contracts are forecasts, not production demand. General coffee assortments still need this cycle's coffee selections. Prepaid scheduling is held rather than guessed.

## General CSV import

1. Create an Orders CSV connection, or choose an existing owning store when source IDs match its API IDs exactly.
2. Upload a UTF-8 CSV, at most 5 MB, 5,000 rows and 80 columns.
3. Map stable order ID, stable line ID, product title, integer bag count, received timestamp with timezone, payment state and fulfillment state. Map net coffee ounces only from an actual per-bag net coffee field.
4. Inspect the preview, confirm the mapping and load it into the inbox. Loading creates no plan. Resolve coffee, bag size, grind and other decisions before selecting orders.

The example download contains fictional data. Do not upload it to a production instance as real demand. The preview expires after 30 minutes; the worker clears expired raw rows while retaining audit metadata. Applying the same preview twice is safe; changing its columns after applying requires a fresh upload. Reusing source IDs lets later refreshes update the same records rather than duplicate them. A CSV from a different shop must use a different owning connection.

## Troubleshooting

Access denied: check the key's order-read permissions and platform entitlement, then edit the same connection. Rate limit: wait before retrying. Public-address error: use a public HTTPS domain; local/private destinations and redirects are intentionally blocked before sending credentials. A store behind a redirect must use its final canonical HTTPS address.

Do not resolve an access error by creating another connection for the same store. Never paste credentials or real order payloads into public issues, screenshots or logs.

## Official references

* [WooCommerce Orders REST API](https://developer.woocommerce.com/docs/apis/rest-api/v3/orders/)
* [Wix Search Orders](https://dev.wix.com/docs/api-reference/business-solutions/e-commerce/orders/orders/search-orders)
* [Squarespace Orders overview](https://developers.squarespace.com/commerce-apis/orders-overview)
* [Shopify Admin GraphQL Orders](https://shopify.dev/docs/api/admin-graphql/2026-10/queries/orders)
