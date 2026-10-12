---
name: sentinel-security-review
description: Use when reviewing Sentinel changes involving secret references, request definitions, persistence, logs, API errors, network policy, or potentially sensitive committed files.
---

# Sentinel security review reference

Review the candidate diff and eligible untracked files against `AGENTS.md` and
accepted ADRs [0006](../../../docs/architecture/ADRs/0006-security-privacy-retention.md),
[0007](../../../docs/architecture/ADRs/0007-outbound-execution-safety.md), and
[0005](../../../docs/architecture/ADRs/0005-opentelemetry-trace-correlation.md)
when those boundaries change. Record the base and candidate identity first.
Architecture requirements live there; this skill provides the review procedure.

| Surface | Evidence to inspect |
| --- | --- |
| Definitions | Tagged-reference syntax/placement, credential-header literals, immutable policies |
| Persistence/change events | Source-to-sink path, redaction before write, safe summaries and rollback |
| Logs/spans/problems | Closed safe fields, exception/input handling and synthetic canary absence |
| Network/runtime | Applicable SSRF/DNS/redirect/TLS/size/timeout and bind/token tests |
| Frontend/artifacts | No secrets in browser settings, fixtures, generated examples or reports |

Start with filenames: `git diff --name-status BASE`,
`git ls-files --others --exclude-standard`, and a scoped `rg -l` search for
`get_secret_value|SENTINEL_SECRET_|Authorization|Cookie|\$secret|model_dump|logging|record_exception`
in affected source files. Inspect suspicious code privately; report paths/lines
and sanitized evidence, never matched credential values, raw bodies or environment
dumps. Pattern hits are leads, not proof; this procedure is not a credential scanner.

For each changed data path, trace untrusted input → validation → domain/service
→ logging/telemetry/persistence/response. Use synthetic canaries in rejected inputs
and inspect all applicable sinks. Existing health tests do not establish catalog
safety. Catalog reads must not resolve references or perform target I/O; references
are permitted synthetic fixture content, not secrets. Keep unrelated valid baggage
allowed while rejecting Sentinel-owned context. M2 static policy validation does
not authorize implementing the later HTTP adapter.

Example finding: high severity, `api/...:42`, rejected header literal reaches a
validation response through raw input serialization; ADR 0006 violated; synthetic
canary reproduced in response; logging/database coverage pending; remove raw-input
echo and add boundary/sink tests. Omit the canary's actual text from the report.

Output: candidate/base identity; reviewed paths; severity/file/line/source→sink/
violated invariant/sanitized reproduction/remediation per finding; exact test
commands and coverage; unresolved scope and residual risk. Distinguish confirmed
leaks, unsupported guarantees and harmless synthetic references. Reviewer reports
production fixes to their owner; acceptance tests require separate ownership and
worktree. No commit, external upload or remote setting change follows from review.
