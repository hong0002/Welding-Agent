# Agent session contract and initialization fix

2026-10-02. Verdict: **AGENT_SESSION_INITIALIZATION_AND_ORIGIN_FIXED**.
No real model inference, native pipeline, simulator or Isaac launch was performed.
Root .env/API key and existing conversation database were not modified.

## Backend contract (running OpenAPI + route/service source)

The running `/openapi.json` lists these methods. Responses currently have an empty
OpenAPI schema (`{}`): no response_model is declared. Fields below are the actual
service/session source contract, also used by frontend types; no API redesign was made.

| Route | Method | Request / required fields | Optional fields | Response | Errors |
|---|---|---|---|---|---|
| `/api/agent/status` | GET | no body | none | enabled, api_key_configured, model, sdk_available, state (DISABLED / NOT CONFIGURED / READY / RUNNING) | server failure possible; no inference |
| `/api/agent/sessions` | **POST** | no required body fields; frontend sends **`{}`** | body may be omitted/null; extra keys forbidden | 201 `{session_id: UUID}` | 403 invalid_request (Origin/query), 422 validation, 405 GET |
| `/api/agent/sessions/{session_id}/history` | GET | path session_id UUID | no body | 200 session_id, active_job_id (UUID/null), messages[{role,text,at}], running | 404 session_not_found, 422 bad UUID, 405 POST |
| `/api/agent/sessions/{session_id}/reset` | POST | path session_id UUID, empty action | body may be omitted/null; extra keys forbidden | 200 history after reset | 403 invalid_request, 404 session_not_found, 409 run_in_progress, 422 validation, 405 GET |
| `/api/agent/chat/stream` | POST | body session_id UUID, message (trimmed nonempty, 1–2000 chars) | job_id UUID/null, clarification_id UUID/null | 200 text/event-stream; assistant_delta, tool_started/completed, workspace_updated, warning, error, done | 403 invalid_request, 404 session_not_found, 409 run_in_progress, 503 agent_not_configured, 422 validation; safe faults also arrive as SSE error |

Origin/query checks run before creating/resetting a session or dispatching chat.
SDK orchestration, same-session/job admission and serialization remain unchanged.

## Actual audit and root cause

Before this fix:

* `api.createAgentSession()` already used POST and JSON `{}` via the shared `json()` helper.
  `request()` preserves that method; history used GET; stream/reset used POST.
  The user's GET `/sessions` 405 is expected, not proof of a frontend GET bug.
* Initialization started history/session creation independently of status, in parallel
  with `GET /status`. Any saved-history error was treated as stale and caused creation.
* All initialization errors, including restoring a missing active job, were caught by
  the generic “Backend 연결을 확인…” message. A READY Agent could still show the inaccurate
  “Agent 설정 후…” note when session creation failed.
* Agent mutations inherited the main default Origin list containing only localhost/
  127.0.0.1:5173. The current root .env and audit-shell WELD_CORS_ORIGINS are unset.
* Read-only live checks: backend8000 and proxy5174 health/status both succeed. A direct
  backend OPTIONS preflight for Origin `http://127.0.0.1:5174` returns **400 Disallowed
  CORS origin**; its status response omits Access-Control-Allow-Origin. The Vite proxy
  itself responds normally. No live session POST/reset/chat was sent.
* Source guard + fake TestClient reproduce the corresponding session POST as
  **403 invalid_request** with the old 5173-only policy and zero Runner calls.

Thus A/B/C/E (GET mismatch, wrapper changing method, missing body, history method mismatch)
were not found. F (misleading generic initialization error) is confirmed, together with
the Origin admission mismatch. D is handled safely but the current browser's saved UUID
and failed network packet were not extracted: do not claim a particular stale session
was the observed failure. Valid-session workspace restoration is a separate failure
path that previously produced the same misleading message.

The frontend port/proxy target was not changed as a fix. Health via5174→8000 works.
The backend **Agent-only default** now permits the four fixed loopback 5173/5174 origins.
An explicit WELD_CORS_ORIGINS policy remains authoritative, including rejection of5174
if omitted. Simulator action Origin checks and main CORS policy retain their prior behavior.
No arbitrary localhost port, wildcard or external origin is allowed by default.

## New lifecycle and safe UX

1. GET Agent status. READY (or RUNNING for another session) plus enabled/key/SDK permits
   initialization; DISABLED/NOT CONFIGURED does not create a session.
2. Restore a valid saved UUID with GET history. Keep its transcript/session.
3. Only explicit 404/410 means stale. Otherwise preserve the ID and show
   AGENT_HISTORY_LOAD_FAILED, without creating another session.
4. Missing/malformed local UUID or stale response: POST `{}`, save returned UUID,
   GET history, enable Assistant. Shared initialization promise avoids StrictMode
   duplicate creation. Storage persistence is optional.
5. A saved running request is reconciled via history polling; controls stay guarded.
   Restoring an unavailable active job produces a workspace warning while chat remains usable.
6. Session errors show fixed safe text: AGENT_SESSION_CREATE_FAILED,
   AGENT_SESSION_ORIGIN_REJECTED, AGENT_SESSION_NOT_FOUND, AGENT_HISTORY_LOAD_FAILED,
   AGENT_STATUS_UNAVAILABLE. An explicit “대화 다시 연결” button retries initialization;
   it never submits/resubmits chat or dispatches a model.
7. Stream transport failure uses AGENT_STREAM_UNAVAILABLE. Recognized backend Agent
   faults use fixed safe messages; clarification reason codes retain existing behavior.
   Raw request/exception/path/secret bodies are not displayed as initialization errors.

All URLs stay relative `/api/...`; no frontend backend host/port or key is introduced.

## Changed files

* `backend/agent_routes.py`, `backend/main.py`: scoped Agent origin defaults; methods/bodies unchanged.
* `frontend/src/agentSession.ts`: selective session restoration and safe initialization errors.
* `frontend/src/useAssistant.ts`: status-first initialization, reconnect and independent workspace restore.
* `frontend/src/api.ts`: HTTP status on APIError, safe stream transport/error messages.
* `frontend/src/components/AssistantPanel.tsx`: accurate configuration/connection notes and reconnect control.
* `tests/test_agent.py`, `frontend/e2e/agent-session.spec.ts`: contract and lifecycle regressions.
* `frontend/e2e/assistant.spec.ts`: model-unavailable fake response now includes its real backend reason code.
* `frontend/playwright.config.ts`: optional test-only ports; defaults unchanged at5174/8001.

Other pre-existing uncommitted simulator capture changes remain as found; they were not
edited by this task. Segment2/Trajectory3/Guided VLA/simulator implementation is unchanged.

## Offline verification and operator action

Backend tests inject FakeRunner/FakeSimulator and forbid OpenAI transport. Browser tests
cover status→POST{}→GET, StrictMode exactly-once creation, saved sessions, stale404/410,
temporary failures without ID loss, disabled Agent, safe create/origin errors and reconnect.
The existing Assistant/SSE/clarification/tool tests remain part of the fake regression suite.

The user's actual frontend5174/backend8000 remain running untouched during tests.
Fake Playwright uses isolated5184/8011 with relative paths; the backend contract test
specifically verifies default Origin5174 admission and explicit-policy rejection.

Final results: **499 pytest passed** (37 Agent-focused), **42 Playwright E2E passed**
(8 new session lifecycle cases), TypeScript/Vite build, compileall and diff check PASS.
The first browser run exposed a test selector matching both the status light and error
paragraph, plus an old uncoded model-error fixture. Selectors were narrowed to the error
paragraph; the fixture now supplies the real model_unavailable code and safe error UI.
All existing fake chat/tool/clarification workflows passed with the final implementation.

Restart the backend to apply the Agent Origin guard change, then refresh the existing
frontend5174 page. Session restoration/creation should enable the Assistant without a
chat request. If an explicit WELD_CORS_ORIGINS is exported, it must include the actual
frontend origin. No key/secret change or storage reset is required.
