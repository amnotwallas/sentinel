---
name: sentinel-feature
description: Use when implementing or fixing a Sentinel feature, assigning a vertical slice, or preparing concurrent backend and frontend work.
---

# Sentinel feature reference

Read root `AGENTS.md` and the accepted milestone first. Task ownership and
handoff fields are defined in [the workflow](../../../docs/development/workflow.md);
M2 dependencies are in [the task plan](../../../docs/development/milestone-2-plan.md).
The task packet is the working contract; link normative architecture rather than
copying it into every prompt.

| Situation | Reference action |
| --- | --- |
| No approved slice or unresolved wire decision | Complete its contract packet before compatibility surfaces |
| Concurrent writers | Assign absolute isolated worktrees, disjoint paths and separate `_test` databases |
| Shared file needed | Coordinator applies proposal or transfers ownership before edits |
| API changes | Backend owns schemas; coordinator owns both generated artifacts; frontend waits for that handoff |
| Slice ready | Return tested candidate identity and evidence, then coordinator integrates |

For a production behavior change, add the lowest-layer failing test, confirm the
expected failure, implement minimally, then run focused and relevant final gates.
Use [quality gates](../../../docs/development/quality-gates.md) and the security
review skill where sensitive data or boundaries change. API transports invoke
services; domain types stay independent of framework/ORM schemas.

Example packet: M2-03 backend owns environment files/tests and its allocated
migration; coordinator owns `api/app.py`, fixture/model registration and generated
types. Frontend tests the integrated project contract in another worktree. Record
the common base SHA, database/ports, incoming interfaces and exact acceptance cases.

Handoff: task ID, changed paths, base/candidate SHA or uncommitted fingerprint,
focused/final commands and results, migration SQL/up/down evidence, generated
contract status, review findings, remaining dependencies and risks. Commit/push/
merge permissions come from the user, not the task's passing tests.

Common mistakes: a new worktree does not inherit uncommitted files; a spawned
agent may share the checkout; a unique Compose project does not replace fixed
host ports. M2 client work does not authorize the M6 authoring UI.
