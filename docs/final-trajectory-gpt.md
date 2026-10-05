# Final trajectory GPT integration

Verdict: **PARTIAL — offline adapter/UI/STP handoff implemented; native retrieval dependency missing.**

`LIVE_GPT_SMOKE_PENDING`. Paid OpenAI, Segment2, Trajectory3, Guided VLA, SSH retrieval and Isaac live calls: **0** during development. Root `.env` and external repositories were not modified.

## 1. Read-only native audit

External root: `D:/Research_and_Paper/2026경남AISW경진대회/code/vlm_final_gpt`.

| Item | Actual source contract |
|---|---|
| Entry | `predict.py:main`, local script; no HTTP inference API |
| Prediction | `predict.py:call_stage` → `client.responses.parse`, structured `Proposal` |
| Model | `config.yaml` and `config_train_selected8.yaml`: `gpt-6-luna` |
| Reasoning | `medium`, max output tokens 5000, SDK timeout 180 s, SDK retries 2; unchanged |
| Stages | GPT rough (target about 9 points, structural 2..33) → GPT corners (2..33) |
| Native inputs | 9 RGB, available annotation polylines rendered red, natural-language instruction, known start XYZ, workpiece categories, retrieved TRAIN images/instructions/teaching actions |
| Cameras | `B/F/L/R/S1/S2/S3/S4/T` in that order |
| Guidance | No native Trajectory3 guidance/reference/YOLO input parameter. Native first-stage GPT rough feeds corners |
| Original dataset | Baseline `metadata.json`, `source_label.json`, `raw_rgb/*_Color.png`, `trajectory.npz` |
| References | `vlm_project2.fewshot_examples.prepare_examples`; native config uses SSH alias `IDEALABv2_key`, resident retrieval, top_k=3 |
| Raw output | `rough.json`, `corners.json`: stage/model/response ID/usage/proposal; Proposal has description, XYZ points, geometric connections, uncertainties |
| Relative frame | `source_robot_start_relative_mm`; add the supplied start exactly once |
| Absolute frame | `source_robot_frame_unaligned_with_isaac`, mm; NPZ `_m` fields are meters |
| Final count | Native `interpolate.py:interpolate_corners` preserves control points/order and produces exactly 33 points |
| Orientation | None. Orientation remains simulator policy, `vla_orientation=false` |
| GT policy | Known start is explicit GT-derived conditioning. Full GT is evaluation only after prediction; `--end` is not used |
| Auth | Native `OPENAI_API_KEY` or `api_keys_path`; integration can use backend root `.env` key without logging/exporting it to the browser |
| Dependencies | numpy, Pillow, PyYAML, pydantic, openai, tqdm; integration also needs h5py/dotenv; native imports fcntl and the sibling retrieval module |

Installed `C:/Users/hong_/anaconda3/envs/py3_12/python.exe` successfully imported openai/h5py/yaml/numpy/PIL/pydantic/tqdm without inference.

**Confirmed blocker:** `../vlm_project2/fewshot_examples.py` is absent. Bounded code-tree filename search found no copy. The original baseline `../RICL/welding_validation_ricl_maskmix_available` is also absent. The web adapter does not require that benchmark baseline: it obtains exact current RGB/label assets and explicitly uses H5[0,:3] as the known start. This does not reconstruct the missing native retrieval implementation. Its internal dependencies and operational readiness cannot be confirmed until the original module is available.

No substitute retrieval, no automatic `--no-retrieval`, no GT mask substitution and no synthetic benchmark baseline were introduced. Native prompts are unchanged. The native developer prompt still describes benchmark GT masks; the input context/view captions explicitly identify this integration's **human-approved web F mask, not GT annotation**. This is a web conditioning adapter, not a claim of benchmark input parity.

## 2. Previous Guided VLA contract

`Workflow.run_guided_vla` → `WorkflowGuidedVLAClient.validate_inputs/check_server/prepare_workflow/execute` → strict `VLAPredictedTrajectory` → VLA_READY.

Guided requests are one F-only multipart request, with guidance Markdown and approved F PNG. T3 reference XYZ remains unregistered and is not a target. Result is exactly 9 finite XYZ mm plus matching 9 GT points/metrics; NPZ stores exact float32 meter conversion. UUID/hash/approval/scene/guidance proof is saved privately. WorkflowPredictionAdapter rechecks this before immutable package copy; native simulator transforms/derived playback/orientation are separate.

Existing endpoints remain:

- `POST /api/weld/{job_id}/guided-vla` (strict Guided VLA, empty body).
- `POST /api/models/guided-vla/check` (selected predictor's check; GPT performs configuration checks only).
- Current preview/preflight/live/frame APIs remain UUID bound.

## 3. Backend abstraction and native execution

`FinalTrajectoryPredictor` defines status, input admission, run, current-result verification and readiness check. `configured_final_predictor` explicitly selects `guided_vla` or `gpt`. Invalid selection fails closed; no fallback. Workflow accepts `final_predictor=`; the historical `guided_vla` slot remains for compatibility/injected tests.

`POST /api/weld/{job_id}/final-trajectory` accepts `{}` only. `run_final_trajectory_prediction` Agent tool has no arguments. Runtime executable/cwd/config/paths/points are never accepted from browser or Agent.

`GPTTrajectoryPredictor` uses the existing validated native F conditioning gate: same current sample/split/9 views, approved mask ID/hash/time, native plan proof, single 8-connected region, and existing >=80% 2-pixel guidance correspondence. It snapshots inputs in a fresh UUID attempt, then launches the fixed owned worker with `shell=False` through the existing owned process/Windows Job Object supervisor. No integration retry loop.

GPT uses an overall 900-second supervisor cap; Segment's camera-marker watchdog is not applied to this different native pipeline. Native SDK timeout/retries are unchanged. Its backend-owned launch explicitly permits the native `OPENAI_API_KEY` environment source; Segment/Rough still strip inherited keys by default. Key values are never placed in argv, manifests or diagnostics.

Worker `gpt_trajectory_entry.py`:

1. Imports external predictor unchanged. Windows fcntl compatibility is injected locally; external files/bytecode are not written.
2. Reads only exact H5 first XYZ before prediction. Reads nine verified source RGBs; overlays the actual approved binary F PNG. Other views stay unannotated.
3. Uses current human language and label workpiece categories in native image/text context. T3 F polyline is used only as a native retrieval shape query (other cameras have empty polylines); it is not injected into the GPT developer prompt or used as generated XYZ. Manifest records this distinction.
4. Calls **native `prepare_examples`**, **native `make_client`**, and **native `call_stage`** for rough/corners. No new trajectory prompt is authored here. SDK settings stay native.
5. Saves each native structured stage before `check_proposal`, then runs **native `interpolate_corners`**, and adds known start. The external predictor's interpolation is part of its source prediction; no extra smoothing/snap/alignment occurs in Welding-Agent.
6. After both calls, reads full exact H5 XYZ for 33-point index-linear evaluation GT and uses native `metrics`. This GT is never an interior model input.

## 4. Output / validation / raw display

GPT normalization is `GPTPredictedTrajectory`: sample/split, model, `source=vlm_final_gpt`, `provider=gpt`, fixed absolute frame/mm, exactly 33 prediction/GT points, connections, ADE/FDE and execution=false. Source native raw stages and normalized `response.json` are separate. NPZ uses float64, preserving native prediction precision in meter conversion. Guided's schema and float32/n9 branch stay strict.

Hard checks: finite XYZ; native 33-point count; frame/units; same sample/split; exact NPZ/response equality and dtype; GT/H5 equality; metric recomputation; current mask/approval/instruction/scene/guidance binding; native source/config hashes during execution; immutable result hashes. `between_segments`/unknown connections block simulator admission. Raw displays split at invalid rows and disconnected/unknown edges, never bridge regions.

**Workspace limitation:** native and existing Guided VLA have no explicit physical workspace bounds or metric maximum-step tolerance. No tolerance was invented. Validation records `workspace_bounds=NOT_SPECIFIED_BY_NATIVE_CONTRACT`. Geometry connection checks and native source interpolation do not establish physical reachability/collision safety. Robot Preview still needs existing sample-specific native IK/FK preflight. Physical execution stays disabled.

`raw_final_prediction` is independent of accepted `vla_prediction`. On malformed/partial/nonfinite/frame/units/provenance failures, native files remain; bounded finite runs can be shown as raw projection XY/XZ/YZ. Foreign sample geometry is retained privately but not overlaid as the current sample. `GET /api/weld/{job_id}/final-trajectory/{artifact_id}/display` returns only current-bound finite runs/frame/units, never paths/reasoning. It rechecks job conditioning and display digest. Browser uses relative `/api` URLs.

Workflow retains ROUGH_PATH_READY on GPT failure; VLA_READY is reused as the historical **final 3D result ready** state only after successful validation. Upstream edits invalidate raw/accepted results. Native failures do not trigger retries. Repeating a successful generic action verifies/reuses the current result. Per-Agent-turn admission remains serialized and prevents a second dispatch. Existing strict Guided endpoint still rejects repeat/out-of-order calls.

## 5. Agent / UI / simulator

Explicit final prediction requests route through the generic tool; questions/status/negations never authorize it. Explicit GPT wording with Guided selected rejects backend mismatch rather than using Guided silently. Safe chat contains only source/model/count/frame/metrics/status, never XYZ arrays or native description/reasoning.

UI selects `GPT Trajectory · Final 3D Trajectory` or `Guided VLA · Final 3D Trajectory` and shows source. Shared instructions call this final 3D prediction. Raw projection remains visible after failed acceptance; buttons do not promote raw output to accepted/simulator-ready state.

Dataset STP/v2 package uses a separate strict GPT33/float64 branch. Legacy current/sample replay keeps its old Guided9 contract and does not admit GPT via that legacy adapter. NPZ is byte-copied, native builder returns derived playback separately, and the pre-GUI stdlib gate rechecks exact provider/count/lineage/hash. Renderer uses `/GPT_PREDICTED_33` and existing **red BasisCurves, linear/nonperiodic/constant width**. `/VLA_PREDICTED_9` stays available for Guided.

P0/P4/P8 capture slots retain their **actual source indices** for both contracts; with GPT33 they are not middle/end aliases. `path_detail` shows the full path. Existing owned MJPEG/latest capture logic/session isolation is preserved. No Isaac launch was used for verification.

## 6. Operator configuration / rollback

Root `.env` was not rewritten. After restoring the original native `vlm_project2` retrieval dependency and its documented configuration, choose explicitly:

```dotenv
WELD_FINAL_TRAJECTORY_BACKEND=gpt
WELD_GPT_TRAJECTORY_REPO=D:/Research_and_Paper/2026경남AISW경진대회/code/vlm_final_gpt
WELD_GPT_TRAJECTORY_PYTHON=C:/Users/hong_/anaconda3/envs/py3_12/python.exe
WELD_GPT_TRAJECTORY_CONFIG=D:/Research_and_Paper/2026경남AISW경진대회/code/vlm_final_gpt/config.yaml
```

Model/reasoning are read from that native config; no Agent model setting is used for coordinates. Backend key stays in root `.env` (or existing native key file). If using Agent for live prediction, its configured run timeout should cover the predictor supervisor (900s); existing example uses `WELD_AGENT_RUN_TIMEOUT=1200`. No secret value should be copied to UI/logs.

Restart backend after operator configuration changes. Dataset sample → Segment2 → human F approval/edit → Trajectory3 + clarification → GPT Trajectory execution → Path Preview → offline Robot readiness → Robot Preview. No automatic simulator/model execution.

Rollback selector: `WELD_FINAL_TRAJECTORY_BACKEND=guided_vla`, then restart. Guided config/token/tunnel remain unchanged. Old packages/results are immutable; ownership code fingerprint changes can require explicit audited descriptor refresh or fresh offline preflight, never automatic reuse/bypass. Revert only this task's code delta if removing the feature; prior raw-display/live-view changes are separate.

## 7. Changed files in this task

- New: `backend/model_clients/final_trajectory.py`, `gpt_trajectory.py`, `gpt_trajectory_entry.py`; `backend/services/final_prediction_proof.py`, `final_prediction_arrays.py`; `frontend/src/components/FinalPredictionView.tsx`.
- Backend wiring/contracts: `main.py`, `schemas.py`, `model_clients/trajectory_contracts.py`, `model_clients/native_process.py`, `orchestrator/workflow.py`, `orchestrator/state_machine.py`.
- Agent: `agent/tools.py`, `context.py`, `decision.py`, `config.py`, `prompts.py`.
- Simulator: `services/simulator_prediction_package.py`, `simulator2_client.py`, `simulator2_gate.py`, `preview_visual_style.py`, `current_vla_isaac_preview.py` (owned only).
- UI: `App.tsx`, `api.ts`, `types.ts`, `agentDecision.ts`, `SimulatorPanel.tsx`, `components/PathPanel.tsx`, `WorkflowStepper.tsx`.
- Tests: new `test_gpt_trajectory.py`, `test_gpt_simulator_handoff.py`, `e2e/final-trajectory.spec.ts`; existing semantic tool-count/labels, native supervisor key-source test and variable-N native fixture helpers updated.
- Docs/config example: this file, README, architecture, `.env.example`.

## 8. Verification and remaining live work

Fake tests cover explicit selection, native input, parse/partial/malformed/nonfinite/frame/units/sample, approval lineage, immutable raw files, failed-but-displayable output, no connected gap rendering, zero native calls on stale approval/questions, duplicate prevention, STP33 exact byte-copy + separate playback + no launch, renderer numeric gate without Isaac imports, UI labels/projection/failure refresh. Existing Guided/Segment/T3/clarification/Agent/live-view regressions are retained.

Verification on 2026-10-03 (offline only):

| Check | Result |
|---|---|
| Initial full pytest | 738 passed before the final supervisor/key-source test additions |
| Final full pytest | 739 passed, 1 failed during temporary fixture `os.replace` with Windows `WinError 5`; no intent/model assertion was reached in that case |
| Failed module recheck | `tests/test_agent_decision.py`: 75 passed, including the failed fixture case |
| GPT/STP/supervisor focused tests | 45 passed after final changes |
| Full fake Playwright | 66 passed, 1 demo-image GET failed with `net::ERR_CONNECTION_TIMED_OUT` |
| Eraser + GPT UI targeted Playwright | 6 passed, including that failed Eraser case and both GPT UI cases |
| Frontend build | TypeScript/Vite passed; existing >500 kB chunk warning |
| compileall / diff check | Passed |

A temporary whole-suite attempt under the repository was unsuitable: the pre-existing capture test requires ASCII staging paths, while this repository path contains Korean characters. It also hit a short Agent timing assertion. Verification returned to an ASCII temporary directory; no product gate/test assertion was relaxed.

No live provider readiness or inference success is claimed. Restore native retrieval code/dependencies, inspect its actual contracts, then perform a separately authorized one-sample smoke. **LIVE_GPT_SMOKE_PENDING**.

**XYZ source = vlm_final_gpt's GPT trajectory predictor**: owned worker calls external `native.call_stage` twice, then external `native.interpolate_corners`; Agent only invokes a no-argument semantic tool and Workflow admission. Live generation remains blocked until native dependency readiness is established.

## 2026-10-05 runtime selection / Agent repair

**GPT_FINAL_PREDICTOR_PARTIAL — GPT_FINAL_TRAJECTORY_RUNTIME_BLOCKED.**

1. **Current Runtime Backend:** running `/api/models/status` and the selector both identify Guided VLA (`backend=guided`, canonical selector `guided_vla`). Agent model is independently `gpt-6-luna`; it does not select the numeric predictor.
2. **Why Guided was selected:** root `.env` has no `WELD_FINAL_TRAJECTORY_BACKEND`, and no process override exists. The factory default is `guided_vla`. Generic deterministic execution also previously emitted `run_guided_vla` for Guided mode, and SDK tools offered both execution tools.
3. **Environment:** unchanged. OpenAI key configured=true; Guided token configured=true. No credential values are in the audit report. Do not set `gpt` until the original native retrieval module and its transitive dependencies are restored and audited.
4. **Agent:** deterministic requests and SDK now use `run_final_trajectory_prediction` regardless of the configured predictor. SDK tools omit the historical `run_guided_vla` callable; its compatibility gate still rejects GPT mode. Explicit GPT wording with Guided configured fails closed. Questions/status do not invoke inference, upstream models, health or Simulator. Duplicate/current-result gates remain.
5. **Native readiness:** `C:/Users/hong_/anaconda3/envs/py3_12/python.exe` imports numpy, Pillow, PyYAML, pydantic, openai, tqdm, h5py and dotenv. With network and OpenAI client construction disabled, importing actual `predict.py` through the owned import bridge raises `ModuleNotFoundError: vlm_project2`. Source contains `call_stage` and `check_proposal`, and imports `interpolate_corners`; these functions are not available as an imported native module until retrieval is restored. Actual config remains `gpt-6-luna`, `reasoning_effort=medium`, rough9/output33, SDK timeout180/retries2. No model/prompt/scorer change.
6. **Original retrieval search:** sibling `vlm_project2/fewshot_examples.py` is absent. Bounded sibling/competition-root source and ZIP inspection found no implementation in `vlm_project2.zip`, `vlm_project.zip`, `vlm_project4.zip`, `11.zip` or `^^.zip`. Existing Segment/T3 retrieval code has another contract and was not substituted. Required next asset is the original `vlm_project2` package containing `fewshot_examples.py`, together with its actual imported modules/config. Its transitive runtime/remote readiness remains unknown. Native config's relative benchmark data/output directories are absent; the owned web worker uses the current bound dataset root and creates a UUID output under this repository's `.cache`, not those benchmark directories. No live input/output attempt was created.
7. **This repair's files:** `backend/agent/{tools,context,decision,service,prompts,welding_agent}.py`; `frontend/src/{agentDecision.ts,api.ts,components/AgentDecisionCard.tsx,components/PathPanel.tsx}`; `tests/{test_agent,test_agent_decision,test_gpt_trajectory}.py`; `frontend/e2e/{agent-decision,final-trajectory}.spec.ts`; `README.md`, `docs/architecture.md`, this document. Existing native GPT implementation, external repositories, root `.env` and simulator implementation were not modified.
8. **UI:** tool progress and AI decision use `GPT 최종 3D 궤적 예측 / Source: vlm_final_gpt` or `Guided VLA 예측`. The additive `final_predictor` event field accepts only fixed enum values; old summaries remain readable. Action labels follow runtime selection; an immutable result retains its actual artifact source even after runtime selection changes. No raw points, paths or reasoning enter chat.
9. **Guided failure evidence:** the latest existing attempt `8fc39cdc-d30e-49a2-bff7-0767fa64065b` is C_PP_03_0001/train/F, reference_in_request=false, endpoint `http://127.0.0.1:18000/v1/predict-guided`. Prior `submission.json` has live_called=true; response/NPZ/metadata/completion are absent. Submission is written before transport, so this alone does not prove a successful HTTP send. Current authorized non-inference `GET /health` returned 200/ready, model ex3-best-ade-epoch-17, waypoints9/dimensions3. Transport merges HTTP errors and JSON decode errors into `GUIDED_VLA_REQUEST_FAILED` without a persisted safe status/timeout cause; response-validation failure before persistence is also possible. **Historical precise root cause is UNKNOWN**, not a confirmed current tunnel/token failure. No prediction POST/retry was made for this repair.
10. **Tests:** final full fake pytest: 776 passed. Fixed-Python actual import audit confirms the native dependency blocker with network disabled. Frontend build/compileall/diff check passed; build retains the existing >500kB chunk warning. Final fake Playwright: 5 passed, covering generic execution, GPT label/summary, duplicate prevention, raw finite-run display, validation admission and artifact-source labels. Pytest also verifies unchanged approved masks and no Guided dispatch in GPT mode. Initial test attempts had temporary-directory access failures and an obsolete SDK fixture tool-count assertion; the fixture now asserts 12 SDK tools with only generic final execution. Final suite uses a fresh ASCII temp path, without weakening product gates.
11. **Restart:** required to load Agent changes. With root `.env` unchanged, a restart still selects Guided VLA. After original dependencies are restored and offline readiness passes, explicitly configure `WELD_FINAL_TRAJECTORY_BACKEND=gpt` and restart again. No automatic fallback/restart.
12. **Live:** **LIVE_GPT_SMOKE_PENDING**. This task: OpenAI/GPT prediction0, Guided prediction0, Segment0, Trajectory0, SSH retrieval0, Simulator/Isaac0. Only a documented health GET was used.

Private safe audit receipts (no credentials/raw reasoning): `.cache/final-predictor-runtime-audit.json`, `.cache/final-predictor-offline-import.json`, `.cache/final-predictor-pytest.log`.
