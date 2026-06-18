# PathScientist / PathLab Web Security — Remediation Plan

> Date: 2026-06-18
> Status: Active — ready to assign
> Source: [`2026-06-18-pathscientist-web-security-audit-results.md`](2026-06-18-pathscientist-web-security-audit-results.md)
>   (22 confirmed, adversarially-verified). Backend (non-web) findings live in
>   [`2026-06-17-pathscientist-code-review-remediation-plan.md`](2026-06-17-pathscientist-code-review-remediation-plan.md);
>   this plan covers the **gateway/web layer** + cross-references the overlaps so nothing is built twice.
> Paths relative to `server/` unless noted.

## 0. How to use
- Each task is assignable: `ID · severity · files:lines · problem · fix · acceptance · tests · effort · depends · owner`.
- Effort: S ≤0.5d, M 1–2d, L 3–5d. Audit finding ids in `(…)` cross-reference the audit doc.
- **Sequencing:** **WS-A (IDOR) is P0 — do it first and ship it on its own.** Then B (RCE) → C (SSRF) → D (traversal) →
  E/F (hardening). A and B can run in parallel by different people.

## 1. Priority snapshot
| Pri | Workstream | Why |
|---|---|---|
| **P0** | A — Access control / IDOR | critical cross-tenant read/download/stop/delete of other users' sessions |
| **P0** | B1 — Checkpoint host RCE | agent-reachable host command execution (= existing plan `A8`) |
| **P1** | C — SSRF | web-reachable (chat) + provider fetch to internal/metadata |
| **P1** | D — Run-download traversal | one download endpoint missing the base-dir guard |
| **P2** | E/F — JWT-in-query, DoS/persistence | hardening / robustness |

---

## WS-A · Access Control / IDOR  (P0 — the priority)

> Goal: a non-admin user must get **403** on any other user's session for get / download / run-download / events /
> stop / resume / delete — including after a gateway restart and for legacy disk-only sessions.

### A1 · CRITICAL · `gateway/routes/pathscientist.py:2297-2301` · effort S · (audit A1)
**Problem:** `_can_access_record` fails OPEN on empty owner: `return not owner or owner == str(user.id)`.
**Fix:** mirror `_can_access_db_session` — `return bool(owner) and owner == str(user.id)` (admin/None already
short-circuit above). Empty/unknown owner ⇒ denied for non-admins.
**Acceptance:** unit test: empty-owner record + non-admin user ⇒ `_can_access_record` is False; owner match ⇒ True; admin ⇒ True.
**Depends:** — **Owner:** ____

### A2 · CRITICAL · `gateway/routes/pathscientist.py` `SessionRecord.summary()` (176-216) + `_registry_payload`/`_save_gateway_session_record` (1543-1548, 1811) · effort M · (audit A1)
**Problem:** `user_id` is never written to the on-disk gateway registry, so registry-reloaded sessions (after a restart)
have `user_id=''` and become world-accessible even with A1 fixed-at-creation.
**Fix:** include `user_id` in `_registry_payload` (and/or `summary()`); on load (`_load_gateway_session_records`,
already reads `user_id` from the JSON) ensure it round-trips. Add a migration/backfill for existing registry files.
**Acceptance:** integration test: create a session as user X → simulate registry reload (new `SessionManager` from disk)
→ the record's `user_id` is X → user Y gets 403.
**Depends:** — **Owner:** ____

### A3 · HIGH · `gateway/routes/pathscientist.py` `_scan_persisted_conversations` (2859-2874), `_hydrate_persisted_record_detail`/`_refresh_persisted_record_detail` (2675-2727) · effort M · (audit A1/#2/#4)
**Problem:** disk-scanned conversation stubs are built with no `user_id` (defaults `''`) ⇒ every user's persisted
conversations under the shared root are accessible.
**Fix:** stamp `user_id` onto each stub — resolve it from the DB row (`AutoResearchRepository.get_session`) or the
persisted `base_state.json`/summary; if the owner cannot be established, **restrict the record to admins** (exclude from
non-admin `list()`/`get()`).
**Acceptance:** test: a disk conversation owned by X is not returned by `_SESSION_MANAGER.get/list` for user Y, and Y
gets 403 on its endpoints; admin still sees it.
**Depends:** A1 **Owner:** ____

### A4 · HIGH · all read/mutate endpoints (`gateway/routes/pathscientist.py` get/download/run-download/events/stop/resume/delete) · effort M · (audit #3)
**Problem:** endpoints resolve via `_SESSION_MANAGER.get()` FIRST and trust `_can_access_record`; the stricter
`_load_db_record` is only reached when `get()` returns None, so an empty-owner in-memory/disk record shadows the DB check.
**Fix:** after `_SESSION_MANAGER.get()` returns a record, **re-verify ownership against the authoritative DB row** before
serving (or rely on A1+A2+A3 making the in-memory owner trustworthy). Pick one and apply uniformly across all endpoints.
**Acceptance:** parametrized test over every endpoint: user Y → 403 on user X's session (in-memory, registry-reloaded,
and disk-only variants).
**Depends:** A1, A2, A3 **Owner:** ____

### A5 · HIGH · `backend/database/repositories/auto_research.py` (get_session / delete_session / get_session_events / get_events_after / get_latest_sequence) · effort M · (audit A2)
**Problem:** repository read/delete queries filter only by `session_id` — zero defense-in-depth.
**Fix:** thread an optional `user_id` into these queries (admins bypass) and pass it from the routes; deny cross-user at
the data layer even if a route check regresses.
**Acceptance:** repo unit test: `get_session(session_id, user_id=Y)` returns None for X's session.
**Depends:** — **Owner:** ____

### A6 · LOW · `auto_research.py upsert_session` (82-86) + `gateway/pathscientist_persistence.py _persist_event` (259-284) · effort S · (audit A3)
**Problem:** `upsert_session` overwrites `user_id` on existing rows; `_persist_event` falls back to `'unknown'` →
silently downgrades a session's owner (data loss / lockout).
**Fix:** never overwrite `user_id` on an existing row (skip it like `id`/`created_at`, or assert it matches); don't fall
back to `'unknown'` for an owned session.
**Acceptance:** test: upsert with a different `user_id` does not change an existing row's owner.
**Depends:** — **Owner:** ____

### A7 · LOW · `backend/pathscientist/dataset/pathlab_registration.py:199-208` + `orchestrator/runner.py:129` · effort S · (audit A4)
**Problem:** ownerless registration creates a **public** dataset (`is_public = user_id is None`) and resolves by name
without an owner filter.
**Fix:** refuse registration when `user_id` is falsy (`status='skipped', reason='no_owner'`); decouple public visibility
from owner identity (explicit `make_public` flag).
**Acceptance:** test: registration with empty `user_id` returns skipped and creates no public row.
**Depends:** — **Owner:** ____

---

## WS-B · Command Injection / RCE

### B1 · P0 · HIGH · `backend/pathscientist/runtime/workspace.py` create/restore/delete_checkpoint (458-519), `_git` (556-558) + `tools/checkpoint.py` boundary · effort S · (audit B1; **= remediation-plan `A8`**)
**Problem:** agent-controlled checkpoint `name` → `tag=f"checkpoint/{name}"` → unquoted `_git(f"tag {tag}")` run through
a shell, host-side even under apptainer → host RCE.
**Fix:** validate `name` `^[A-Za-z0-9._-]{1,64}$` at the `CheckpointExecutor` boundary **and** `shlex.quote` every
interpolated tag (or argv + `shell=False`). **Do this once** — it is the same task as remediation-plan `A8`; track it
there and reference here.
**Acceptance:** `checkpoint create "x; touch pwned"` is rejected and never reaches git; no `pwned` created.
**Depends:** — **Owner:** ____ (coordinate with A8 owner)

### B2 · LOW · `workspace.py _SubprocessWorkspace.execute_command` (115-139) · effort S · (audit B2)
**Fix:** execute argv lists (`shell=False`); keep the env-flag gate; document it must never be enabled in a multi-user
deployment. **Owner:** ____

### B3 · LOW · `backend/pathscientist/runtime/sandbox.py:156` · effort S · (audit B3; = remediation-plan `A4`)
**Fix:** `shlex.quote` `workspace_dir` and `script_path` in the `bash -lc` string; validate `script_path` is
workspace-relative (the `RunExperimentAction.script_path` validation is remediation-plan `A5`). **Owner:** ____

---

## WS-C · SSRF

### C0 · P1 · build the shared egress guard first · NEW `server/.../net_guard.py` (or reuse remediation-plan `SHARED-1`) · effort M
**Build:** `validate_external_url(url)` — scheme∈{http,https}; resolve host and reject loopback/link-local
(169.254/fd00)/RFC1918/0.0.0.0/metadata; a fetch helper with `follow_redirects=False` that re-validates each redirect
hop. One implementation, used by both C1 and C2 (and the backend providers in remediation-plan `B-NET`).
**Acceptance:** unit tests: metadata IP, localhost, private ranges, `file://`, redirect-to-internal → rejected; public
https → allowed. **Owner:** ____

### C1 · P1 · MEDIUM · `gateway/routes/chat_pdf_sources.py` `download_pdf` (417-480), `_fetch_lightweight_web_markdown` (1015-1016) · effort S · (audit C1)
**Problem:** web-reachable SSRF — user-steered `[READ_ARTICLE]` URL fetched with `follow_redirects=True`, no host filter.
**Fix:** route both fetches through `C0.validate_external_url` + no-redirect-revalidation; optionally allowlist
publisher/academic domains.
**Acceptance:** a `[READ_ARTICLE]` to `http://169.254.169.254/...` is refused; a redirect to an internal host is refused.
**Depends:** C0 **Owner:** ____

### C2 · P1 · MEDIUM · `backend/pathscientist/dataset/providers/direct_http.py:86` (+ zenodo/scidb/gdc fetchers) · effort S · (audit C2; = remediation-plan `B-NET`)
**Fix:** apply `C0`/`SHARED-1` to every provider `sess.get/post`. **Do once** with remediation-plan `B-NET`.
**Depends:** C0 **Owner:** ____ (coordinate with B-NET)

---

## WS-D · Path traversal

### D1 · P1 · MEDIUM · `gateway/routes/pathscientist.py _build_run_artifact_zip` (4277-4334) · effort S · (audit D1)
**Problem:** unlike `_build_session_artifact_zip` (4246-4249) and `_delete_session_workspace` (1699-1707), the run-zip
builder omits the `workspace.is_relative_to(base_dir)` containment check.
**Fix:** add the same guard at the top of `_build_run_artifact_zip`; centralize the confinement in
`_resolve_session_workspace` so every consumer is confined by construction. Also tighten `_resolve_artifact_source`'s
`data_output_dir` allowed-root so it can't widen to a non-base path.
**Acceptance:** test: a record whose persisted `workspace_path` points outside the base dir yields 404/empty on run
download, not arbitrary file reads.
**Depends:** — **Owner:** ____

---

## WS-E · Auth hardening

### E1 · P2 · LOW · `backend/auth/dependencies.py` (371-401) + `gateway/routes/pathscientist.py` SSE/download deps (3626-3631, 3657-3661, 3691-3695) · effort M · (audit E1)
**Problem:** full session JWT accepted via `?token=` (logs/history/Referer leakage); amplified by the IDOR.
**Fix:** issue **short-lived, single-purpose, session-scoped** download/SSE tokens instead of the full JWT in the query;
or move to header/HttpOnly-cookie auth for these endpoints. Set `Referrer-Policy: no-referrer` on these responses and
scrub `token` from access logs.
**Acceptance:** SSE/download still work; the URL no longer carries a reusable full session JWT.
**Depends:** — **Owner:** ____

---

## WS-F · DoS / robustness

### F1 · P2 · LOW · `gateway/routes/pathscientist.py:75` (`StartPathScientistSessionRequest.question`) + `gateway/pathscientist_persistence.py _session_payload` (381) + `_json_safe` · effort S · (audit F1)
**Fix:** `Field(..., min_length=1, max_length=4000)`; `_truncate_text(research_question)`; add a byte budget +
recursion-depth guard to `_json_safe`. **Owner:** ____

### F2 · P2 · LOW · `gateway/pathscientist_persistence.py _run_best_effort` (1418-1425) · effort M · (audit F2)
**Fix:** replace the global-lock + 5s-blocking wait with a bounded per-loop async queue/worker (no fleet-wide
serialization); `future.cancel()` on timeout; surface terminal-state / model-registration failures (retry/flag) instead
of silently swallowing. **Owner:** ____

---

## 2. Verification / regression
- Add a **two-user IDOR test matrix** (the most important deliverable): for each endpoint × {in-memory, registry-reloaded,
  disk-only} × {owner, other-user, admin}, assert 200/403 as appropriate. This guards A1–A5 against regression.
- Run from `pathlab/pathlab-client/server`:
  `OPENHANDS_SUPPRESS_BANNER=1 backend/pathscientist/.venv/bin/python -m pytest tests/test_pathscientist_routes.py tests/test_auto_research_repository.py -q`
- Each P0 task ships with a regression test that fails before and passes after.

## 3. Tracking checklist
| ID | WS | Pri | Sev | Effort | Owner | Status |
|---|---|---|---|---|---|---|
| A1 | A | P0 | Critical | S | | ☐ |
| A2 | A | P0 | Critical | M | | ☐ |
| A3 | A | P0 | High | M | | ☐ |
| A4 | A | P0 | High | M | | ☐ |
| A5 | A | P0 | High | M | | ☐ |
| A6 | A | P1 | Low | S | | ☐ |
| A7 | A | P1 | Low | S | | ☐ |
| B1 | B | P0 | High | S | | ☐ (=plan A8) |
| B2 | B | P2 | Low | S | | ☐ |
| B3 | B | P2 | Low | S | | ☐ (=plan A4) |
| C0 | C | P1 | — | M | | ☐ (=plan SHARED-1) |
| C1 | C | P1 | Medium | S | | ☐ |
| C2 | C | P1 | Medium | S | | ☐ (=plan B-NET) |
| D1 | D | P1 | Medium | S | | ☐ |
| E1 | E | P2 | Low | M | | ☐ |
| F1 | F | P2 | Low | S | | ☐ |
| F2 | F | P2 | Low | M | | ☐ |

## 4. Notes
- **A1+A2+A3+A4 must land together** to actually close the IDOR — fixing only `_can_access_record` (A1) leaves the
  registry/disk empty-owner records, and fixing only persistence leaves the fail-open check. Treat WS-A as one P0 deliverable.
- No SQL injection was found (ORM is parameterized) — keep `text()`/f-string queries out of these repositories.
- `import_session_bundle` must stay off the web surface (CLI migration only); if ever exposed, force the caller's id.
