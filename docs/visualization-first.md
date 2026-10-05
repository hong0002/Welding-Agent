# Visualization first

Display does not grant validation, approval, simulation admission or robot playback authority. Original files, approval lineage and source XYZ remain immutable. Physical execution is disabled.

## Gate audit (2026-10-05)

| Location / gate | Class | Policy |
| --- | --- | --- |
| `model_display.read_masks/read_path`: bounded PNG / numeric finite runs / dimensions | A DISPLAY | Keep raster bounds; invalid rows split runs. Unknown trajectory frame/dimensions retain numeric geometry in an isolated viewer, never guess a current overlay. Validation and approval do not hide geometry. |
| `model_display.verified`: owned immutable display-copy hash and job/scene binding | A DISPLAY | Keep copy integrity; native acceptance provenance is separate. Foreign evidence uses isolated viewer, no current overlay. |
| `Workflow._read_display`: native acceptance hash failure | B VALIDATION | Revoke candidate/downstream authority, retain independently sealed raw display. |
| `Workflow.refine_mask`: binary/empty/removed-pixel constraint | B VALIDATION, C APPROVAL | Preserve failed raw result; do not replace accepted mask or auto-approve. |
| `native_candidate/native_preview`: correspondence/direction/proximity/connected regions | B VALIDATION | Preserve independent raw segments; do not bridge or promote rejected candidate. |
| `Workflow.admit_job`, Agent mutation/approval guards | C APPROVAL | Preserve mutation authority; read-only result viewers are independent. |
| `StateMachine.clear_trajectories`: upstream edits | B VALIDATION | Invalidate current authority and archive display references; explicit previous-result viewer only. |
| GPT `validate_inputs`: initial H5 XYZ finite | B VALIDATION, E ROBOT | Invalid absolute origin permits explicitly relative visualization; never relabel zero as actual robot origin. |
| GPT retrieval adapter failure | B VALIDATION | Visualization-only fallback segment2_adapter → local → none; record chain, no Guided VLA fallback. |
| GPT stage parsing/interpolation/completion/arrays/proof | B VALIDATION | Preserve every renderable stage/raw partial; completion proof still requires valid absolute final artifact. |
| GPT display reader: current conditioning hash | A DISPLAY | Archived view remains accessible; stale cannot overlay current scene or launch current preview. |
| `simulator2/stp._inputs` final proof/frame gate | D SIMULATOR, E ROBOT | Existing strict robot branch preserved; separate owned geometry-only preview accepts renderable display evidence. |
| `simulator2/stp` native IK/FK/URDF/orientation/placement checks | E ROBOT | Keep. Geometry-only branch does not request IK or robot playback. |
| Current preview gate/job lease/Job Object/session capture binding | D SIMULATOR | Keep owned-process and package integrity for all preview modes. |
| `LocalStorage._write_json`: Windows atomic replacement contention | Persistence, not promotion | Retry only Windows permission/sharing errors for at most 150 ms, then raise. Same temporary file and atomic replacement; never fall back to a partial/non-atomic write or retry a model call. |
| Frontend raw layer/viewer conditions | A DISPLAY | Use renderability, not acceptance/approval/readiness; explicit stale/source/stage selectors. |
| Agent `ACTION_FAILED` with preserved output | A DISPLAY | Report OUTPUT_AVAILABLE_UNVALIDATED and counts; no hidden reasoning/prompt/coordinates in chat. |

Common presentation fields: OUTPUT_EXISTS, OUTPUT_RENDERABLE, OUTPUT_VALIDATED, OUTPUT_APPROVED, SIMULATION_DISPLAYABLE, ROBOT_PLAYBACK_READY. They are read-only presentation facts, never workflow transition authority.

## Verification

Automated checks use fake transport/processes only. Live smoke is separate and bounded; no retries, model downloads, external repository writes or physical execution.

Final automated results:

- Full pytest: **877 passed**, 158.93 s (`.cache/viz-first-full-final-04.log`). Earlier runs hit Windows `os.replace` WinError 5 at different temporary snapshots; bounded atomic replacement retry fixed this without a non-atomic fallback.
- Related Playwright suites: **18 passed**; after the last Geometry/source-count UI adjustment the two affected specs passed again (**2 passed**). Tests use the explicit fake app factory, not the live backend.
- Frontend TypeScript/Vite build: **PASS**. Existing bundle size warning remains (681.33 kB JS before gzip).
- Backend compileall and `git diff --check`: **PASS**.
- Focused Windows atomic-save/refinement/display suite: **40 passed**; permanent permission failures retain the original snapshot and propagate the error.

## Implementation report

| Requested item | Implementation |
| --- | --- |
| 1. Previous blockers | Absolute H5 start, retrieval availability, final completion/schema, upstream invalidation, generic Agent failure, and strict simulator admission were conflated with output availability. |
| 2. Removed display blockers | Independently sealed raster/finite runs are read without granting candidate authority. NaN rows break runs. Current identity and original evidence integrity still matter. |
| 3. Segment2 raw | Owned display copies of PNG/polyline remain visible on validation failure; separate current/previous output catalog. |
| 4. Refinement raw | Failed constraint/partial/empty results retain raw evidence and the explicit AI Refined from Manual label. Rejected output does not replace the edited mask or acquire approval. |
| 5. Trajectory3 raw | Direction/proximity/correspondence failures retain independent native segments. Unknown frame and foreign evidence use an isolated viewer. No region bridge or NaN bridge. |
| 6. GPT stages | Rough, corners, final and public structured-response partial XYZ are preserved. Choose the latest renderable stage; malformed later stages do not erase earlier geometry. No hidden reasoning or free-text numeric guessing. |
| 7. Relative visualization | Invalid absolute start uses explicit `gpt_start_relative_visualization_mm`, visualization origin only. No absolute NPZ/completion proof/GT metrics/robot promotion is produced for that branch. |
| 8. Geometry Preview | New owned renderer draws each finite XYZ run in a neutral source-frame Isaac scene; mm-to-m display conversion only. No workpiece registration, robot, IK or physics stepping. Relative/degraded orange, absolute red. |
| 9. Robot strict gates | Existing dataset_stp/dataset_v2 Robot admission, proof, sample/approval binding, source geometry, IK/FK, frame and orientation policy remain. Geometry/Robot window changes require an explicit stop. Physical execution stays disabled. |
| 10. Stale/foreign | Upstream invalidation archives display references. Previous outputs remain explicitly selectable, with no current overlay or current simulator launch. Foreign outputs are isolated. |
| 11. UI states | Six presentation flags, source/revision/stage selectors and XY/XZ/YZ projections. New renderable output yields `OUTPUT_AVAILABLE_UNVALIDATED` instead of generic action failure. Geometry captures identify Latest capture, not live streaming. |
| 12. Tests | See matrix below. Models, SDK transport, retrieval and native processes are fake in automated tests. |
| 13. Live smoke | See bounded receipts below. Existing raw geometry/capture passed; the fresh GPT request stopped at its first SDK connection error. |

## Regression matrix

| Scenarios | Evidence |
| --- | --- |
| 1–2 Segment failure / refinement constraint violation visible, approval blocked | `test_model_display.py`, `test_mask_refinement.py`, `semantic-mask.spec.ts` |
| 3–5 Trajectory proximity failure, two regions, partial NaN | `test_model_display.py`, `test_native_output_preview.py`, `native-output-preview.spec.ts`, `model-display.spec.ts` |
| 6–11 Normal final, invalid start, retrieval chain, bad corners, malformed schema, invalid final | `test_gpt_trajectory.py`, `test_gpt_trajectory_retrieval.py`, `test_visualization_first.py`, `final-trajectory.spec.ts` |
| 12 Absolute path/robot unchanged | `test_simulator_stp_client.py`, `test_simulator2_client.py`, `simulator-stp.spec.ts` (fake native/preflight evidence) |
| 13–15 Relative/raw path independent from robot/IK/workspace warnings | `test_visualization_first.py`, `visualization-first.spec.ts`; relative geometry also exercised in real Isaac as described below |
| 16 Stale available / current overlay prohibited | `test_visualization_first.py`, `test_model_display.py` |
| 17–20 Separated states, warning completion, raw viewer, normal workflow | Agent regression suites and the seven related Playwright specs |

## Bounded live smoke, 2026-10-05

| Smoke | Result |
| --- | --- |
| A Segment2 raw display | Existing real B_PP_03_0001 raw F PNG returned HTTP 200; no Segment2 rerun. |
| B Failed/unvalidated manual refinement | Fake workflow/browser regression passed. A fresh paid refinement smoke was not performed; no failed-refinement live artifact was found in the bounded recent-job audit. |
| C Multi-region Trajectory3 | Two independent raw segments/no bridge passed offline and in fake browser E2E. Existing recent approved live jobs had one segment; no new mask approval was fabricated to dispatch this smoke. |
| D GPT final | Existing B_PP raw GPT 5 points rendered in the actual web projections. Fresh final completion not established by this smoke. |
| E GPT relative/degraded | Existing `source_robot_start_relative_mm` raw path was displayed. One fresh C_PP_03_0001 invalid-start attempt admitted relative visualization, completed retrieval, then failed on the first rough SDK request with `APIConnectionError`. No new points, no retry. |
| F Simulator geometry | PASS: existing B_PP raw 5-point geometry, dataset_stp configuration, owned Isaac session, exact XYZ preserved, robot_motion=false, physics_stepping=false. 1280×960 path_detail PNG served HTTP 200 and displayed in the real frontend. |
| G Robot strict gate | PASS for unaccepted raw artifact: HTTP 409 `CURRENT_PREVIEW_ARTIFACT_INVALID`, no Robot process launch. Actual IK-failure live playback was not attempted. |

Fresh GPT attempt: `093cb7ad-9a36-4856-ae1e-35a460c0ad40`, job `d5fce6ef-1312-49cf-9c3b-905424bfd174`.
Retrieval started 09:31:12.688296Z, completed 09:31:24.822763Z; rough started 09:31:25.084339Z.
HTTP result 503 `GPT_TRAJECTORY_PROCESS_FAILED` after 16.33 s. Approved mask ID/time remained unchanged.
Private receipt: `.cache/viz-first-live/4f9a6746-c5fc-4996-9a80-27ac603d5a12/final.json`.

Geometry job: `72b8f9bb-a38b-4855-aead-f863f52b0f22`; artifact `65822d00-a386-403e-b003-de0abfcb520e`.
Owned Isaac session: `091991f1-2627-4830-b31e-36f3e94fc98e`; request `710d0876-21ca-4037-a5fd-4e8fead9218a`.
Receipts/capture: `.cache/viz-first-live/a8d6ef10-1bdb-40b5-9b01-95cc15a6a77c/`.
Browser verification used real backend GETs and a fake conversation bootstrap; all browser POSTs were blocked.
Cleanup verified STOPPED, pid=null, can_stop=false; captures unavailable after stop. Files remain preserved.

## Use and limits

1. Open **경로 계획 → 모델 출력 보기 / 이전 결과 보기**. Select Segment2, edited/refined mask, Trajectory3 or current/previous GPT output.
2. For current GPT geometry, select Rough/Corners/Final and XY/XZ/YZ. Failed validation does not grant approval or remove renderable geometry.
3. Open **시뮬레이션 → 생성된 XYZ 보기 · Geometry Preview**. The owned source-frame window supplies **Latest capture**. Stop it before switching to the strict sample-scene Path/Robot branch.
4. Robot readiness remains a separate proof/frame/IK/policy decision. No physical robot endpoint is enabled.

Policy-related files:

- Display extraction: `backend/model_clients/geometry_display.py`, `model_display.py`, `gpt_trajectory.py`, `gpt_trajectory_entry.py`, `gpt_trajectory_retrieval.py`.
- Lifecycle/presentation: `backend/schemas.py`, `backend/orchestrator/workflow.py`, `state_machine.py`, `backend/agent/context.py`, `decision.py`, `tools.py`.
- Owned preview/API: `backend/main.py`, `backend/services/output_catalog.py`, `geometry_preview.py`, `current_preview_gate.py`, `current_preview_runtime.py`, `preview_startup.py`, `storage.py`, `backend/geometry_isaac_preview.py`.
- UI: `frontend/src/App.tsx`, `api.ts`, `types.ts`, `agentDecision.ts`, `SimulatorPanel.tsx`, `components/OutputBrowser.tsx`, `FinalPredictionView.tsx`, `PathPanel.tsx`, `SimulatorViewport.tsx`.
- Regression/docs: `tests/test_visualization_first.py`, `test_model_display.py`, `test_atomic_storage.py`; related GPT/refinement/semantic tests; `frontend/e2e/visualization-first.spec.ts`, `semantic-mask.spec.ts`, `final-trajectory.spec.ts`; README and architecture/final-trajectory docs.

External Segment2/Trajectory3/GPT/simulator/Isaac sources and assets were not modified. Root `.env` was not changed by this policy implementation.

An unidentified or corrupt sealed display copy, no output, unparseable data or all-nonfinite points still reports an unavailable/error state. That is a data/integrity limitation, not a validation/approval display gate. Unknown XYZ units remain visible in the web viewer, but cannot be scaled for Isaac by guessing.

The optional rough-derived 33-point visualization and an interactive 3D web viewer were not added; preserved native rough runs and XY/XZ/YZ projections are available. Geometry Preview intentionally does not invent H5/OBJ registration for relative or unvalidated output. Existing strict sample-scene Path/Robot integration remains separate.

Remaining live work: establish fresh GPT completion after resolving the connection failure; operator-reviewed multi-region input and a real refinement result are needed for B/C live coverage. No automatic paid retry was scheduled. Verdict: **PARTIAL**.

For identifiable, safely readable preserved artifacts: A=NO, B=NO, C=NO, D=NO, E=NO, F=YES, G=YES.
These answers are implementation/offline-policy conclusions, not a claim that every live failure scenario was reproduced.
