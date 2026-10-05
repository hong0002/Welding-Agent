# Universal result visibility — 2026-10-05

Results are inspectable independently of acceptance and execution authority. The
catalog never promotes a raw, stale, foreign or rejected result into an approved
mask, registered prediction, robot proof or executable command. All physical
execution remains disabled. External repositories and root `.env` are unchanged.

## DISPLAY BLOCKER AUDIT

Repository searches covered frontend controls/viewers, backend read endpoints,
workflow invalidation, native display sealing, model adapters, simulator admission,
frame/provenance checks and owned-session capture. Search record:
`.cache/universal-display-audit-search.txt`.

| Location / former blocker | Final behavior |
| --- | --- |
| `App.tsx` current preview/state/dirty-mask guards | Guards still govern editing and execution. Output Browser retrieves current and historical outputs separately. A failed refresh preserves loaded evidence. |
| `ModelOutputSummary`, native Canvas layer: validation or approval | Raw finite segments and decodable PNGs remain visible. Foreign output uses its own viewer. Validation/approval are separate labels. |
| Segment/refinement pixel/removed-region constraints | Failed raw output is sealed and catalogued; the current edited mask is retained, no redetection fallback or automatic approval. |
| Native trajectory correspondence/direction/proximity | Blocks acceptance only. Every segment and finite run is displayed independently, with no bridge across regions or NaN/Inf. |
| `StateMachine.clear_trajectories` downstream invalidation | Archives native trajectory, GPT display, accepted prediction and 2D preview snapshots. Removes authority, retains viewer references. |
| Rejected 2D rough output before storage | Stores a display-only historical snapshot before raising validation failure. Original accepted workflow state is not advanced. |
| GPT rough/corners/final schema or completion failure | Public numeric output is captured before acceptance. Each stage is catalogued separately. Native rough interpolation may produce a clearly labelled Derived Visualization on corners failure. |
| GPT H5 start unavailable | Relative visualization only; ABSOLUTE START UNAVAILABLE. No fabricated absolute origin, NPZ completion proof, metrics or robot authority. |
| GPT retrieval failure | Existing visualization chain adapter → local → none, one attempt per mode. No Guided VLA fallback. |
| Provider connection failure with zero new points | Safe attempt status is stored. Previous/raw/stale geometry remains selectable. No new geometry is invented. |
| Current-provider-only GPT reader | Backend-neutral owned display reader and orphaned-attempt recovery support old results after provider changes. |
| Old Guided VLA receipt/provenance mismatch | Original owned JSON/NPZ geometry is available with UNVERIFIED warning; current execution proof is not relaxed. |
| Current-only source filter | Explicit job-bound previous outputs, historical prediction receipts and simulator source/playback artifacts are catalogued. Foreign sample identity prevents current overlay, not isolated inspection. |
| `SimulatorPanel` strict readiness and disabled Geometry/Path split | One Path Preview button uses renderability. Registered absolute uses the Scene branch; raw/relative/stale uses isolated geometry; unavailable runtime leaves the web viewer accessible. |
| Current simulator/frame/IK/robot admission | Optional for path visualization. Strict Robot admission remains unchanged. No second renderer is launched automatically after a scene-launch attempt fails. |
| Owned package/process/capture security | Remains strict. v2 isolated packages seal exact finite runs and source identity independently of current approval/state. Arbitrary browser paths/commands are rejected. |
| Legacy `/preview-current-vla/path` and v1 package | Retained as the strict registered-scene compatibility contract. The universal UI uses `/path-preview`; the legacy endpoint is not the general result viewer. |
| Read-only result API acceptance gate | `/model-outputs` and `/outputs/{artifact}/display` require owned readable data, not approval or validated/current state. |
| Global Agent-busy fieldset | Does not disable result selection/projection/Path access. While mutations are locked, the Path button opens the web viewer; robot and launch mutations remain guarded. |
| Native output copy size/type/hash checks | Retained only for unreadable/corrupt/unowned bytes. Original native acceptance hashes do not control independently sealed display geometry. |

The remaining legitimate unavailable cases are absent bytes, unreadable/corrupt or
unsupported image data, zero numeric points, all nonfinite points, and a response
containing no public geometry. Safe stage/status metadata remains visible. Hidden
reasoning, internal prompts, secrets, absolute paths and credentials are excluded
from catalog responses.

## Contract and operation

Each row exposes OUTPUT_EXISTS, OUTPUT_RENDERABLE, OUTPUT_VALIDATED,
OUTPUT_APPROVED, CURRENT_RESULT, STALE_RESULT, SIMULATION_VISUALIZABLE,
ROBOT_PLAYBACK_READY and PHYSICAL_EXECUTION_READY. The last is always false.
The old SIMULATION_DISPLAYABLE field remains a compatibility alias.

Open **경로 계획 → 모델 출력 보기 / 이전 결과 보기**, or **시뮬레이션**.
Choose Current, Previous or Rejected / Raw. Masks use their original PNG;
2D segments retain region/run boundaries; XYZ supports XY/XZ/YZ projection.
Foreign and stale artifacts are isolated and never automatically overlaid.

**현재 경로 보기 · Path Preview** automatically chooses REGISTERED_SCENE,
RELATIVE_FRAME, SOURCE_FRAME or WEB_SOURCE_FRAME. Runtime configuration,
validation, approval, workspace and IK warnings do not disable this button when
XYZ exists. An already-owned preview may still require stopping before another
Isaac mode starts; its exact geometry is already accessible in the web viewer.

**Robot Preview** retains current sample, absolute frame, mask approval, package
integrity, orientation, IK/FK and source-proof requirements. It does not become
available because a result has been viewed. Orientation remains simulator policy;
`vla_orientation=false`, `physical_robot_executable=false`.

API changes:

- `GET /api/weld/{job}/model-outputs`: safe grouped output metadata and finite runs.
- `GET /api/weld/{job}/outputs/{artifact}/display`: optional `output_kind` and
  `stage_index` identify stage/source/playback; no accepted-state requirement.
- `POST /api/simulator/path-preview`: fixed job/artifact UUIDs, output kind and stage
  index only; returns status plus `path_view`. Browser commands/paths are forbidden.
- Immutable `geometry-preview-v2` is visualization-only. The original v1 and
  registered Scene/Robot contracts remain available for rollback.

## Verification

Fake/offline tests cover unapproved and rejected PNG/refinement, unchanged accepted
mask, finite runs around NaN, disconnected regions, rough/corners/partial/final,
relative/unknown frames, stale/foreign sources, provider-failure retention,
historical Guided VLA and source/playback separation, immutable v2 packages,
registered versus isolated routing, unavailable runtime, IK warnings, zero second
launch attempts and browser-path rejection. Real model calls are not used.

Final verification:

- Full pytest: **897 passed**, 168.98 s (`.cache/universal-complete-final-04.log`).
  Final corrupt simulator-array metadata regression: **1 passed**
  (`.cache/universal-sim-metadata-05.log`).
- Full Playwright scope: **76 scenarios**. First full run passed 75; the one
  failure expected the previous empty-state label. Updating that assertion and
  rerunning both legacy simulator scenarios passed **2/2**
  (`.cache/universal-playwright-full-03.log`,
  `.cache/universal-playwright-legacy-final-04.log`). No functional test was skipped.
- Frontend build, backend compileall and `git diff --check`: PASS. Vite retains
  the existing large-chunk warning.

Separate actual UI smoke reused job `72b8f9bb-a38b-4855-aead-f863f52b0f22`,
artifact `65822d00-a386-403e-b003-de0abfcb520e`, B_PP_03_0001. Real backend
result reads were used; conversation bootstrap was a read-only fixture. All model
POSTs were blocked. Exactly **one** Path action was allowed. Earlier smoke-helper
startup failures occurred before any Path/model request.

| Live check | Result |
| --- | --- |
| A: unapproved Segment2 raw PNG | VISIBLE |
| B: Trajectory3 raw geometry | VISIBLE |
| C: available GPT raw result | VISIBLE |
| D: Raw/Relative Path button | ENABLED |
| E: simulator geometry capture | SUCCEEDED, 1280×960, RELATIVE_FRAME |
| F: Robot blocked while path visible | PASS |

Source XYZ remained exactly **5 points**, with identical finite runs and frame.
`robot_motion=false`, `physics_stepping=false`, `vla_orientation=false`;
orientation is simulator policy. Owned session
`35a98c48-ad22-4d76-b12e-35cbb2b0b48b` was stopped: pid=null, STOPPED and
frames unavailable after stop. Evidence:
`.cache/universal-live/46162b2d-6ffc-4c2a-9f66-1ab3d3fe9f44/`.
New OpenAI/Segment/Trajectory/Guided VLA calls made by this development task: **0**.
Rejected refinement, foreign/stale data, malformed stages and IK failure branches
were verified with fake/offline fixtures; the live smoke did not create new model
failures or new predictions.

## Changed files and deployment

- Backend contract: `main.py`, `schemas.py`, `model_clients/geometry_display.py`.
- Catalog/recovery/view routing: `services/output_catalog.py`,
  `services/visibility_artifacts.py`, `services/visibility_path_preview.py`,
  `services/geometry_preview.py`, `services/current_preview_gate.py`,
  `geometry_isaac_preview.py`.
- Preservation/stage capture: `orchestrator/state_machine.py`,
  `orchestrator/workflow.py`, `model_clients/gpt_trajectory.py`,
  `model_clients/gpt_trajectory_entry.py`.
- UI: `App.tsx`, `SimulatorPanel.tsx`, `api.ts`, `types.ts`,
  `components/OutputBrowser.tsx`, `components/FinalPredictionView.tsx`.
- Tests: `tests/test_universal_visibility.py`; frontend E2E universal visibility,
  visualization-first, final-trajectory, family-preview, simulator-stp and simulator.
- Documentation: README, architecture and this audit.

Existing unrelated working-tree edits were preserved. No external project or
root `.env` was changed. Backend was reloaded for the successful UI smoke. A later
user-initiated Assistant run temporarily postponed the final reader-hardening
reload. After that run completed, the owned idle backend was reloaded successfully.
Final health=ok; the generic raw display API returned 200 and the original 5 points;
simulator state=STOPPED, pid=null.

Final verdict: **UNIVERSAL_RESULT_VISIBILITY_READY** for readable, job-bound owned
outputs. A=NO, B=NO, C=NO, D=NO, E=NO, F=NO, G=YES, H=YES, I=YES. This is a
visibility result, not a claim of new inference correctness or robot safety.
