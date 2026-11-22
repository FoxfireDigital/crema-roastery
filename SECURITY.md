# Security

Use HTTPS through a trusted proxy, keep database/app ports private, create unique accounts and install updates. Staff have broad operational access; superusers can export sensitive business records. Payroll rate access is separately granted. This is one roastery per installation, not tenant isolation for mutually untrusted businesses.

The application includes CSRF checks, signed review forms, stale-edit checks, replay protection, login limits, private caching and a nonce-based script policy. Inline styles are permitted. These controls do not replace an independent security audit. The optional Artisan helper prepares files and asks before loading; hardware safety remains the operator’s responsibility.

Do not include credentials, customer records, screenshots of private data or exploit-ready production details in public issues. Report suspected vulnerabilities using [GitHub private vulnerability reporting](https://github.com/FoxfireDigital/crema-roastery/security/advisories/new). If that facility is temporarily unavailable, keep sensitive details private until a confidential reporting channel is available.

Check dependency advisories before each release and update pinned versions deliberately. A first public launch and any paid hosting offering should receive an independent review of authentication, proxy configuration, access boundaries, backup recovery and merchant data handling.

The proposed scope and evidence requirements are in [docs/SECURITY-REVIEW.md](docs/SECURITY-REVIEW.md). That checklist is preparation, not a completed independent assessment. Built-image inspection and component notices are described in [docs/IMAGE-REVIEW.md](docs/IMAGE-REVIEW.md).
