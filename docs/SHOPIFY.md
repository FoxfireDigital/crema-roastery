# Shopify setup

Create and release your own merchant-authorized Shopify app. Use the exact callback PORTAL_BASE_URL/shopify/callback/ and enable read_orders; read_products enables product checks. Approve released permissions in the store. Older order access may require additional approval; orders CSV remains available.

Enter the store’s original myshopify.com domain, app client ID and secret on More → Shopify connection; authorize from that store. Credentials are encrypted in the database using a key derived from the instance Django secret. Preserve that secret with backups. Tokens and client secrets are never part of business-record CSV exports.

The connection reads orders/products. Its optional webhook registration creates notification subscriptions, not order/payment/fulfillment changes. Customer names are opt-in and require appropriate Shopify approval. Subscriptions owned by Shopify’s official subscription app are not assumed accessible through a generic read scope; import the subscription export for upcoming delivery forecasts. Renewals are actual orders and deduplicate by their Shopify ID.

An independent publicly distributed Shopify app would need its own Shopify approval, merchant privacy handling and required compliance webhooks before broad installation. This package supplies self-hosted merchant-configured connections; it does not reuse any developer’s existing app or keys.
