# Security policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting flow from the repository **Security** tab. Do not disclose a suspected vulnerability in a public issue, discussion, pull request, fixture, or pack.

Include the affected version or commit, operating profile, reproduction steps, impact, and any relevant logs with secrets and private standards content removed. The maintainers will acknowledge the report through GitHub's private advisory channel and coordinate remediation and disclosure there.

## Scope and data boundary

The current pre-release supports synthetic fixtures and locally authorized public-source standards, including Distribution Statement A material. It is not authorized for classified information, CUI, ITAR-controlled content, proprietary standards, or other restricted material. A local installation does not create legal permission to process or redistribute content.

Security-sensitive behavior includes pack and source-catalog validation, PDF parser limits, encrypted-document handling, path handling, rights-policy separation, package/source integrity, authorization and revocation, cursor binding, and evidence completeness. Single-document compilation rejects encrypted PDFs; manifest-driven corpus compilation accepts only empty-password decryption and preserves the original encrypted source bytes and that fact in the extraction report. StandardsForge never executes embedded document actions. Model execution remains host-owned; StandardsForge supplies read-only MCP evidence tools and interpretation boundaries but makes no hosted-service or restricted-deployment claim. The local stdio MCP adapter is not a multi-user network service.
