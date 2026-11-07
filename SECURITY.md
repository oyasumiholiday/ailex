# Security Policy

## Reporting

Security vulnerabilities should be reported through [GitHub Private Vulnerability Reporting](https://github.com/oyasumiholiday/ailex/security/advisories/new). Do not include credentials, private source, personal data, or exploit details in a public issue.

If private reporting is unavailable, open a public issue containing only a request for a private contact channel. Do not post the vulnerability details there.

## Supported Version

Until the first stable release, security fixes target the latest default-branch versions of Ailex and IntentIR. Release-specific support periods will be documented when versioned Packages are published.

## MCP Dependency Update (2026-11-07)

If you use IntentIR's optional MCP server, update the dependencies in the virtual environment that runs it. See the [Japanese upgrade guide](docs/DEPENDENCY_SECURITY_2026-11-07_JA.md). This update does not replace previously published alpha artifacts or update existing installations automatically.

## Review Standard

Every release uses [SECURITY_QUALITY_CHECKLIST_JA.md](SECURITY_QUALITY_CHECKLIST_JA.md). The complete immutable review criteria are stored in [docs/SECURITY_QUALITY_REVIEW_CRITERIA_JA.md](docs/SECURITY_QUALITY_REVIEW_CRITERIA_JA.md).
