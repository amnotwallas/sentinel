---
name: sentinel-pr-prepare
description: Use when preparing a Sentinel pull request, commit candidate, integration handoff, or reviewable local change summary before publication.
---

# Sentinel PR preparation reference

Use [the PR template](../../../.github/PULL_REQUEST_TEMPLATE.md) and
[integration gates](../../../docs/development/workflow.md). Prepare concrete
local contents first; publication permissions come from the user's instruction.

| Field | Evidence |
| --- | --- |
| Scope and target | Task/milestone, approved base, actual branch and remote |
| Candidate | Commit SHA, or tracked diff digest plus eligible untracked paths/hashes |
| Verification | Exact commands/results/counts against that candidate |
| Compatibility | Migration SQL/up/down, schemas/generated types and relevant ADR |
| Review/risks | Findings/resolution, unrun checks, blockers and runtime limits |
| Remote CI | Exact pushed SHA, run URL and all three job results when available |

Read-only identity commands: `git status --short --branch`, `git remote -v`,
`git rev-parse HEAD`, `git rev-parse BASE`, `git diff --name-status BASE`,
`git diff --check BASE`, and `git ls-files --others --exclude-standard`.
Replace `BASE` with the agreed SHA; do not silently choose a different review base.

For an uncommitted candidate, record `git diff --binary BASE | shasum -a 256`
and a sorted manifest of every eligible untracked path with its SHA-256
(`shasum -a 256 PATH`). Record deletions via the tracked diff and review untracked
files separately: Git diff omits them. Capture these identities before and after
validation; changed contents invalidate affected evidence. HEAD alone does not
identify an uncommitted candidate. Keep manifests/bodies outside the candidate
(for example `/private/tmp`), so they do not fingerprint themselves.

Example local handoff: title describing the final behavior, body from the template,
base/HEAD/diff/untracked identities, changed paths and exact gate results. A
dependency branch's passing checks are not the integrated candidate's evidence.
Label user-reported CI separately from an inspected run; do not invent URLs.

Optional independent review is supported by installed `codex review --uncommitted`
or `codex review --base BRANCH`; use the corresponding approved base and review
reported findings. A read-only QA session is another available option. Review
output cannot substitute for actual tests or security evidence.

Without commit/push/PR authorization, leave changes unstaged and return the local
title/body and proposed contents. Do not stage just to include untracked files.
`gh` is absent on the audited installation; an authenticated GitHub interface or
correct-account connector can publish later if explicitly authorized. Repository
visibility and remote settings are outside PR preparation.
