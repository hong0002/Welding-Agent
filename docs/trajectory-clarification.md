# Trajectory3 clarification chat

Explicit native questions now continue in Welding Assistant. A partial output is
not accepted as a plan. Workflow remains `INSTRUCTION_READY`,
`native_output.status=PARTIAL_NATIVE_OUTPUT`, and
`planning_status=NEEDS_CLARIFICATION`. Rough3D and Guided VLA remain blocked.

## Native contract audit

The external `vlm_trajectory3/schemas.py` defines RefinedTask and DetailedPlan
`status=ready|needs_clarification` and `clarification_question_ko`. RefinedTask's
`direction_preference` is a string; SegmentDecision uses `forward|reverse`.
There is no native top/bottom enum. In `cot.py`, a refiner clarification saves
`refiner.json` and exits normally with `--once`, before retrieval/planner. A
planner clarification saves `iteration_001/clarification.json` and also returns.
External source/config/output files are not modified by this feature.

The adapter publishes only the explicit status/question fields. It does not
publish assumptions, refined instruction, search text, prompt, reasoning, CoT
or raw native JSON. A missing/invalid/unsafe question retains the ordinary
partial-output state; an invented question is never substituted.

## Persisted state and provenance

`WeldJob.trajectory_clarification` exposes a UUID, safe question, source stage,
pending status, creation time and optional direction choices. Agent workspace
summaries expose `clarification_required`, `clarification_question` and
`planning_status`, without filesystem paths or native point arrays.

Private, write-once `native_context/<UUID>.clarification.json` binds the question
to job/sample, mask ID, binary/file hashes, actual approval timestamp, native
artifact/session ID and immutable native output proof hash. It also retains
`original_instruction` and the current instruction snapshot. Verification
rechecks native/scene/mask/session evidence and the explicitly saved question
before consuming a reply. Existing proven partial jobs are restored on read;
the old report/proof and native files are preserved byte-for-byte.

An explicit answer first creates a write-once
`<question UUID>.<claim UUID>.clarification-claim.json` with status `claimed`,
`original_instruction`, `clarification_answer`, `resolved_instruction`, approval
binding and answer time. A draft runs only Rough3D under the existing storage/job
locks; the original pending job is retained until the attempt settles. Only a
validated plan or a new explicit native clarification creates the final
`<question UUID>.clarification-answer.json` with status `consumed`, retaining its
UUID in `clarification_history`. Each claim has a separate immutable outcome.
Failure preserves native output and a private failed-job snapshot, restores the
original pending question/instruction, and records a safe reason and `retryable=true`.
There is no automatic retry. A later explicit answer creates a new claim; unknown
or incomplete outcomes block dispatch with `CLARIFICATION_RECOVERY_REQUIRED`.
Mask/instruction/mode edits invalidate the current
question and downstream results; old evidence remains stored. A quick reply
carrying an outdated UUID is rejected. This retains the existing single-process
file-storage scope and job/session admission guards.

## Human answer policy

The backend handles pending replies deterministically, before the SDK Runner.
No orchestrator GPT call is needed to choose an answer. Examples recognized:

| Human reply | Web semantic direction |
|---|---|
| 위에서 아래로 / 위쪽 끝에서 시작해서 아래로 | top_to_bottom |
| 아래에서 위로 | bottom_to_top |
| 왼쪽에서 오른쪽으로 | left_to_right |
| 오른쪽에서 왼쪽으로 | right_to_left |

Direction choices derived from the explicit native question establish the allowed
axis. “화면에서 이음선이 세로로 보입니다…위에서 아래로 용접할까요…” and
“…위쪽 끝에서 아래쪽 끝으로 진행할까요…” work without a separate lexical
requirement for `방향`, `시작` or `어느 끝`. Arrow replies are also supported.
The current minimal resolver supports explicit directional questions. Ambiguous,
conflicting, negative, generic planning/VLA requests or unsupported question
types return the same safe question without a native attempt. “그쪽으로” and
“알아서” never select a direction. A question about another semantic topic is
displayed but requires extending that topic's explicit reply contract.

Web direction vocabulary is separate from the native schema. For the current
vertical case, the only transmitted instruction is:

> 표시된 이음선의 위쪽 끝에서 시작하여 아래쪽 끝으로 용접한다.

The previous left-to-right text is retained in provenance, never appended to
this resolved instruction. Region selection remains unchanged. Native receives
this Korean text through its existing instruction CLI argument; no new native
enum or additional prompt is injected. Vertical validation uses endpoint Y;
native point coordinates/order remain unchanged. Dummy preview supports vertical
row sampling and independent regions. Native Rough2D remains horizontal-only
and rejects vertical directions before model dispatch.

## One-answer execution boundary

Only Trajectory3 runs after a clear answer, using the exact current approved F
mask and its original approval timestamp. No Segment, mask regeneration or human
reapproval occurs. The existing approved-mask adapter creates a fresh immutable
native input projection from that approval. Native output uses a fresh session;
the original partial session is not overwritten.

A validated ready plan returns `ROUGH_PATH_READY` and `planning_status=READY`.
Guided VLA still requires a separate explicit action. A repeated native question
creates a new pending UUID and displays the new question. There is no automatic
retry or loop. Settled failed attempts keep the original pending question for a
new explicit answer; concurrent/consumed/stale claims cannot relaunch it.
Existing native SDK timeout/retry configuration is unchanged.

## Safe UI reasons and diagnosed reply

SSE and HTTP retain allowlisted reason codes: `CLARIFICATION_STALE`,
`APPROVAL_CHANGED`, `CLARIFICATION_PROVENANCE_MISMATCH`,
`CLARIFICATION_ANSWER_UNSUPPORTED`, `CLARIFICATION_RECOVERY_REQUIRED`,
`TRAJECTORY3_ADMISSION_FAILED`, `TRAJECTORY3_NATIVE_FAILED`, `TRAJECTORY3_TIMEOUT`,
`TRAJECTORY3_OUTPUT_INVALID`, and `TRAJECTORY3_NEEDS_CLARIFICATION_AGAIN`.
The UI displays these beside safe messages. A workspace refresh failure does not
replace a received native error code; it shows a separate refresh warning.
No path/hash/raw prompt/reasoning/exception text is added to chat.

Read-only diagnosis on 2026-10-01: latest job
`9256ee42-ea9c-41fa-8a63-a8ac98be195a`, sample `B_PP_03_0001`, F mask
`8da16044-632d-4e7b-9e8c-246d321e8496`, approved
`2026-10-01T10:18:12.928191Z`, pending question
`b00dd0e7-3a1d-423c-85ff-75109d83b53d`.
Safe user-visible transcript stores “위에서 아래로” at 10:22:33 UTC; the
backend repeated the same question. Approval/question provenance verifies.
No answer receipt, resolved instruction or fresh native session was saved.
The old keyword guard returned early despite valid `top_to_bottom` parsing and
explicit vertical choices: **C / RESOLVED_INSTRUCTION_FAIL** (silent no-op,
no stored backend error code). The same guard blocked the previous B_PR planner
question in job `46e7f3fd-7962-4fe4-b47e-321353a9584a`.

Original session: `.cache/native-models/outputs/rough3d_v3/20261001_191829_653414_B_PP_03_0001`.
Original log: `.cache/native-models/diagnostics/383a6f9d-b19f-4461-ba24-e1b28055afe2.native.log`.
It ran before the reply: process start 10:18:27.864 UTC, REFINE 10:18:29.918,
CLARIFY 10:18:41.800, exit=0 and cleanup at 10:18:42.076 (14.219 seconds).
`refiner.json.status=needs_clarification`; query guidance exists, while retrieval,
reference preparation, planner, plan and planner clarification were not reached.
The reply did not rerun native. This repair did not change that job, approval,
question/proof, native files or transcript. No real model/simulator was invoked.

## Web use

Assistant shows the native question and `[위 → 아래] [아래 → 위]` quick replies
for an explicitly vertical question. Suggestions do not select a direction.
Quick replies send the same human text as chat, plus `clarification_id` on the
existing SSE request. Typed replies use the same backend handler. Edited Canvas
drafts must be resolved before replying; this flow does not auto-sync/reapprove
the approved F mask. Pending path panels show partial output, response waiting,
disabled plan generation and blocked Guided VLA. Existing partial visuals remain
available. Reload restores the persisted conversation's current job and question.

For latest job `9256ee42-ea9c-41fa-8a63-a8ac98be195a`, restart the updated backend and
refresh the web page. In the same conversation, the restored question is:

> 화면에서 이음선이 세로로 보입니다. 이음선을 따라 위에서 아래로 용접할까요, 아래에서 위로 용접할까요?

Click `[위 → 아래]` or send “위쪽 끝에서 시작해서 아래로”. This explicit web
reply is the live Trajectory3 authorization. No live rerun was performed during
implementation. Original instruction, approved mask, native artifact hashes and
the original output proof were checked unchanged during offline restoration.

## Offline verification

`tests/test_trajectory_clarification.py` covers A–I: refiner/planner questions,
actual Runner tool-close lifecycle, typed replies, unchanged approval and files,
consistent resolved text, Trajectory3-only/new-session attempts, ready state,
repeated questions, ambiguity without dispatch, stale/upstream/tamper rejection,
safe fields and legacy restoration. Real OpenAI clients/processes are blocked.

`frontend/e2e/trajectory-clarification.spec.ts` uses the explicit fake app to
verify initial chat question, pending path/VLA gates, reload persistence,
ambiguous replies, quick/typed answers and exact fake native call counts.
No real Segment/Rough/OpenAI/SSH/VLA/Simulator/Isaac operation is executed.

Verification after the reply repair on 2026-10-01: full pytest **425 PASS**;
targeted clarification suite **29 PASS**. Full Playwright run: **29 passed,
2 failed** (an existing response-disposal fixture failure and a new test that
expected the optional native overlay before enabling it). After correcting the
overlay assertion, the focused browser run passed **4 tests**, including the
previously failing approval test and all three clarification tests. Frontend
build, backend compileall and diff whitespace checks passed. Tests use fresh
temporary directories inside this repository; existing user evidence is intact.

Verdict: **CLARIFICATION_RESOLUTION_BUG_FIXED_OFFLINE_PASS**. Live replanning
remains unverified until the next explicit human reply.
