# Strict Robot Preview restoration

The unified Robot button used to require cached `robot_preview_ready` and a promoted `VLA_READY` artifact. Missing cached readiness therefore routed an absolute source into the Demo mapper, even though the existing native client can prepare its IK/FK solution on demand. Absolute multiview GPT outputs also remained in the display-only lifecycle and could not enter the original package adapter.

The unified action now prioritizes current-sample absolute `source_robot_frame_unaligned_with_isaac` output and calls the existing strict client directly. Guided 9-point and GPT 33-point NPZ sources use the same `DatasetSimulatorStpClient`, native `run_welding_sample.prepare(..., layout='stp')`, sample H5/OBJ resolver, STP reference environment, source-to-scene transform, fixed initial fixture orientation, native densification, IK/FK and existing Isaac renderer. No anchor, scale or Demo workspace is applied. Relative/previous isolated viewers and explicit Demo remain available. A strict native error is surfaced without silently launching Demo.

A current display-only absolute GPT export can use those existing native numeric files without obtaining mask approval, changing Workflow state, rewriting completion evidence, or granting physical authority. Package construction byte-copies its original NPZ. Source/result binding and existing numeric/asset checks remain in place. Approved-F Guided VLA admission is unchanged. The existing descriptor-only migration recognizes the recorded successful Robot renderer release; source NPZ/native solution/old descriptor are retained. UI shows `STRICT ROBOT PREVIEW` or `DEMO ROBOT PREVIEW` from the actual admitted session.

Changed implementation files:

- `backend/services/robot_demo.py`: strict priority without cached-readiness gate.
- `backend/services/current_vla_preview.py`, `backend/services/final_prediction_proof.py`: simulation-only GPT source binding, separate from approval promotion.
- `backend/services/simulator2_client.py`, `backend/services/simulator2_gate.py`: common 9/33-point native package path and display-only source lifecycle.
- `backend/refresh_preview_ux.py`: existing metadata-only migration for the exact prior successful release.
- `frontend/src/SimulatorPanel.tsx`, `frontend/src/components/SimulatorViewport.tsx`: strict/Demo labels and sample-scene information.
- `tests/test_strict_robot_restore.py`, `frontend/e2e/multiview-robot-demo.spec.ts`: fake/native-output regressions.

2026-10-05 validation: 67 focused strict/STP/GPT-handoff/descriptor tests and 4 fake UI tests passed; frontend build, backend compileall and stdlib STP gate import passed. No model inference was called. Full regression was omitted.

One real web Robot action reused successful Guided artifact `7bdec2fd-a3dc-478e-b623-ca8ae448f44d`, job `512f8695-3e1e-4e0f-81ca-bac392ef50d8`, sample **B_PR_03_0004**. Immutable package `298a9efb-14d2-403e-9ac9-42c887da32bf` and its original native IK solution were reused without recalculation. Session `da840344-2ef1-4084-ae72-351b5bb06e44`, request `ab7158f6-879f-4c62-8b59-92dcc27cb19a` completed 18 playback points from 9 unchanged source points, captured all requested images, and displayed three web live-view samples. Actual RB10 link FK transforms were applied at each waypoint. Maximum joint delta: 0.00664173 rad; measured tool-tip displacement: 66.1773 mm; maximum FK target error: 0.00002023 mm. The exact sample workpiece, STP table, RB10 and ATU01035 tool were visible; predicted path used a connected red BasisCurves line. Physics stepping and physical execution remained disabled. The owned preview was stopped after verification.

Live evidence: `.cache/strict-restore/attempt-1791204667424/result.json`, `live-0.png` through `live-2.png`, `strict-latest-viewport.png`; numeric evidence: `.cache/strict-restore/offline-proof.json`. GPT absolute 33-point strict handoff was verified with fake native output; no current completed absolute GPT artifact was available for a second live run, and no new GPT inference was requested.

Backend was safely restarted on port 8000. The frontend on 5174 uses HMR. Usage: select a current absolute result → **시뮬레이션 → 로봇 시뮬레이션 보기**. If native IK cannot complete, inspect its safe reason; it will not replace the absolute path with Demo coordinates. Stop the current window before switching modes. Root `.env` and all sibling source/assets were left unchanged.


## Current prediction binding audit — 2026-10-05

Verdict: **PARTIAL**. Code selection/proof is implemented; the current model output is relative/partial, not an absolute Final. Earlier Guided B_PR_03_0004 success above is historical evidence and is not the current prediction in this audit.

Actual latest selection traced from the owned preview descriptor (no current browser tab was exposed):

| Field | Value |
| --- | --- |
| job_id | `0cd7fb78-a79e-4064-9bee-56d04b3c7b04` |
| prediction_artifact_id | `d54384aa-4740-45c9-a661-62c5e6820c89` |
| prediction_source | `vlm_final_gpt`, provider `gpt`, Raw Partial Corners |
| attempt_id | `66e5abce-d921-46af-9c22-c5b83c3e04a1` |
| selected stage | `gpt_stage`, index `3` |
| source_point_count | 9 |
| coordinate_frame | `gpt_start_relative_visualization_mm` |
| units | mm |
| current native status | PARTIAL / GPT_TRAJECTORY_PROCESS_FAILED |

### Changes and source trace

The previous strict branch dropped stage_index, which could silently launch the artifact's full Final instead of selected stage XYZ. It now passes the entire backend-owned selected row. `DatasetSimulatorV2Client.run` (inherited by STP) compares those XYZ against adapter source bytes before native math and against the verified package before submission. Differences return `CURRENT_PREVIEW_SELECTED_SOURCE_MISMATCH`; no other predictor or Demo fallback is invoked. A new immutable descriptor stores selection identity and numeric hash without rewriting source, package, native solution or old descriptor.

Default catalog/UI selection prioritizes current GPT over an older accepted predictor; explicit selection persists. Previous/stale/foreign outputs and saved playback remain in the original viewer but are excluded from Robot launch. UI shows Mode, Prediction Source/Artifact, Source Points, Robot Playback Points and MODEL PREDICTION / TRANSFORMED FROM MODEL PREDICTION. Frame/gallery binding also requires the selected stage. Offline preflight controls cannot prepare another predictor when GPT is selected.

Strict source flow: current native attempt trajectory.npz → byte-identical immutable prediction package → external prediction_targets(predicted_path_m) → rigid source_to_scene → native densify_poses → IK/FK. `/GPT_PREDICTED_33` or `/VLA_PREDICTED_9` BasisCurves receives these transformed original N points. Its actual authored Vec3f values are read back and stored in waypoints.npz. Source/package/playback-parent numeric hashes and inverse-transform geometry are checked. Missing renderer evidence for an explicitly selected source fails completion. Strict accepts only rigid SE(3), never Demo mapping.

GT audit: H5 trajectory is read for native scene/placement/orientation metadata and GT frame/metric checks. `welding_prediction.prediction_targets` tiles a policy orientation but replaces all XYZ with transformed predicted XYZ. Native raw target positions and densified positions are independently checked against the prediction. `planned_tcp_xyz_world_m` contains comparison GT; it is never selected by this renderer/playback. `/GT_REFERENCE_ONLY` is a separate green comparison curve. Red points use predicted_path_m; RB10 targets use the checked native tcp_pose array. Native's no-prediction GT branch exists for offline scene checks, but current Robot admission always supplies the prediction package and rejects prediction_input=false. No external native files were changed.

### One actual current-artifact run

Exactly one new Isaac launch; zero Segment/Rough/GPT/Guided model calls. Mode **DEMO**, explicitly transformed from the current relative GPT output. Original 9 source points were saved before launch and remained byte/numerically unchanged. Source 9 → actual red Demo curve 9 → derived playback 9. All three parent hashes:

`d18293f92f324f25e6924443c4338e2b37c57c2eb2040cb0b60c3c3a38b05a9f`

Demo inverse-mapping maximum error: 0.0000324845 mm (USD float32 quantization). FK tip maximum error: 3.12173e-13 mm. Robot motion and capture succeeded. Owned process was stopped. A verifier script import-path error occurred after successful native completion; its checks were completed separately READ-ONLY from the saved evidence, with no second launch.

Session: `ff8054cd-375e-4528-88ff-de7d956ea06a`; request: `804a2972-5ba4-4c98-8a2e-24d225a6eae8`.

Evidence under `.cache/current-prediction-audit/live-d43d8832-2e73-465c-bcb3-d3d4d27b2fc9/`: prediction-before.npy, selection-before.json, action.json, result.json. Actual USD/report/capture under `.cache/simulator/current-previews/sessions/<session>/outputs/<request>/`.

`PLAYBACK_PARENT_IS_CURRENT_PREDICTION=YES`.
`PATH_SOURCE_IS_CURRENT_PREDICTION=NO` for this Demo's red curve; `PATH_TRANSFORMED_FROM_CURRENT_PREDICTION=YES`. Original source-frame viewer is unchanged. This run does **not** prove strict exact-sample STP/OBJ placement. Current absolute Final is missing, and no GT, old Guided artifact or arbitrary transform was substituted to manufacture readiness.

### Verification and remaining work

Focused fake tests: current-prediction source, strict restoration, universal visibility and capture completion — 56 passed. Earlier focused Demo/descriptor checks also passed (57 tests in the first run). Five Playwright fake cases passed; frontend build and compileall passed. Three accepted-result regression fixtures were made explicitly approved-F (`mask_conditioning_views=['F']`); default multiview/unapproved remains display-only. No full pytest was run.

Changed integration files: backend/services/prediction_path_evidence.py, robot_demo.py, simulator2_client.py, simulator2_gate.py, current_preview_runtime.py, preview_capture_result.py, output_catalog.py, visibility_path_preview.py; backend/current_vla_isaac_preview.py, demo_robot_isaac_preview.py, refresh_preview_ux.py; frontend/src/SimulatorPanel.tsx, components/OutputBrowser.tsx, api.ts, types.ts. Tests: test_current_prediction_source.py, test_strict_robot_restore.py, test_universal_visibility.py, e2e/current-prediction-source.spec.ts, e2e/multiview-robot-demo.spec.ts. README/architecture documentation updated. Root .env, external simulator sources/assets and original prediction are untouched.

Remaining: a complete finite current absolute prediction is required for the requested exact-sample Strict scene playback. This turn did not call a predictor to obtain it. UI: select the actual model output → inspect Original Prediction → Robot Preview; relative results say DEMO, absolute compatible results say STRICT. A mismatch is an explicit error, never substitution.

A (current live red curve unchanged XYZ): NO, it is the labelled Demo transform. Strict code preserves prediction XYZ with only its existing rigid scene transform.
B (playback parent is current prediction): YES.
C (GT used as path source): NO.
D (teaching/reference path substituted): NO.
E (GPT selection uses GPT artifact): YES.
F (Strict applies Demo scaling/translation): NO.

## Full sample scene restoration — 2026-10-05

**FULL_SAMPLE_SCENE_PREDICTION_PLAYBACK_READY**

The simplified Demo omitted workpiece/table creation. Demo now resolves exact current H5/OBJ and calls the same native sample placement and `layout='stp'` environment functions as Strict. `sample_scene.py` renders both modes' workpiece, table/legs, ground and robot pedestal identically; both retain RB10/ATU01035 and prediction-derived red curves. The common overview is also the default web capture. Existing live MJPEG, immutable packages, selected-stage binding and manual stop remain intact. No new approval/readiness gate was added. Original prediction, external sources/assets and root `.env` were not modified.

| Actual live verification | Demo | Strict |
|---|---|---|
| sample | B_PR_03_0001 | B_PR_03_0004 |
| job | 0cd7fb78-a79e-4064-9bee-56d04b3c7b04 | 512f8695-3e1e-4e0f-81ca-bac392ef50d8 |
| artifact | d54384aa-4740-45c9-a661-62c5e6820c89 | 7bdec2fd-a3dc-478e-b623-ca8ae448f44d |
| source | GPT Raw Partial Corners, gpt_stage index 3, relative mm | existing Guided absolute prediction, immutable meter NPZ |
| source / playback count | 9 / 9 | 9 / 18 native interpolation |
| table / exact workpiece / RB10 / tool / red path | all present; captures visually checked | all present; captures visually checked |
| robot movement / web live / latest capture | PASS / 2 live screenshots / PASS | PASS / 2 live screenshots / PASS |
| path / playback parent is current prediction | YES / YES | YES / YES |
| GT used as playback | NO | NO |
| new model calls / actual Isaac launches | 0 / 1 | 0 / 1 |

Demo session `7538904e-1a96-40c9-9a7d-49e3bfe63edb`, request `c8f33eeb-c3b4-4615-93a4-dec79ea54e17`. Source and playback-parent XYZ hash both `d18293f92f324f25e6924443c4338e2b37c57c2eb2040cb0b60c3c3a38b05a9f`. Exact B_PR_03_0001 H5/OBJ came from the configured Other/Other dataset's Butt/PR(Plate-Round)/03(3mm)/B_PR_03_0001 directories. The 628-vertex/1252-face workpiece bounds were [0.835,-0.075,-0.010] to [0.885,0.075,0.090] meters. H5 contributes placement metadata only; scene snapshot excludes GT XYZ and robot targets.

Strict session `37789234-5e89-434f-bafc-ff4d8644bd0e`, request `52adf70e-73a8-4489-b0b1-434bfb7fc4c0`. Source and playback-parent hash both `4a4d7982eb9ecb8e0396ed01bc63839c40c6152b45d7c39920336ede1aea836f`. Strict uses only native rigid placement, densification and IK/FK. This is a separately selected existing Guided artifact, never a substitution for the relative GPT Demo.

One preliminary Strict HTTP admission was rejected before Isaac launch: the viewer read server decimal-mm JSON, which differed by 5.578994755e-8 m from the stored float32-meter NPZ. Guided viewers now read that exact immutable playback NPZ. No matching tolerance or source value was changed. A focused regression verifies the representation contract. A known-release descriptor-only refresh preserved native/source/IK files and generated a new descriptor. There was no automatic retry wrapper and no extra Isaac launch. Both owned sessions were stopped and runtime is STOPPED/pid=null.

Focused pytest: 58 initial tests passed; after the Guided representation correction, 35 relevant tests passed, including the new regression. Fake Playwright: 5 passed. Frontend build and backend compileall passed. Full pytest was not run. Backend restarted on 8000 (PID 49640); frontend 5174 served both live smoke UIs and proxy health was OK.

Changed files for this restoration: backend/services/sample_scene.py, robot_demo.py, prediction_path_evidence.py, visibility_artifacts.py, simulator2_gate.py; backend/demo_robot_prepare.py, demo_robot_isaac_preview.py, current_vla_isaac_preview.py, simulator2_prepare.py, refresh_preview_ux.py; frontend/src/SimulatorPanel.tsx and components/SimulatorViewport.tsx; tests/test_full_sample_scene.py, test_current_prediction_source.py, frontend/e2e/multiview-robot-demo.spec.ts; README.md and docs/architecture.md.

Evidence: `.cache/full-sample-scene/DEMO-f729e16c-7949-453e-8879-538b19246de4/` and `STRICT-e97fe46d-228c-44b9-8b5e-619fe523e1f4/` contain source-before.json, action/result JSON, web live and latest screenshots. Native reports, actual authored USD, waypoint arrays and captures remain under `.cache/simulator/current-previews/sessions/<session>/outputs/<request>/`. Demo additionally records prediction stage/source, transform, parent hash and exact scene assets in its immutable descriptor. The previous partial/strict evidence is preserved.

User flow: select the desired current output → Original Prediction viewer → Robot Preview → Live/latest capture (click capture to enlarge) → Stop before switching windows. UI says `Scene: CURRENT SAMPLE · STP`, current sample, and `GT PATH: NOT USED FOR ROBOT PLAYBACK`. Relative/raw output stays explicitly DEMO; this does not promote it to absolute/validated output. STP reference environment retains the existing native table/pedestal approximation. Physics/physical execution remains disabled.

A=YES; B=YES; C=YES; D=NO; E=YES; F=YES; G=YES.

## New authoritative simulator_final audit — 2026-10-05

**SIMULATOR_FINAL_INTEGRATION_PARTIAL**

The requested standalone prerequisite failed. Per the explicit stop condition, no SimulatorFinalClient, backend selector, native compatibility patch, environment switch or web integration was implemented. Current backend remains dataset_stp, STOPPED/pid=null. External simulator_final source/config/assets and root `.env` were not modified. One completed owned web preview was stopped through its own backend API to release the runtime lease. No discovered external process was terminated.

### Native contract and comparison

Authoritative native root is `D:/Research_and_Paper/2026경남AISW경진대회/code/simulator_final` (flat, no nested simulator directory). Docs: `WELDING_SAMPLES.md`, originally Linux `env_isaaclab`. Persistent entrypoint: `run_welding_simulator.py` → `run_rb10_trajectory_with_ATU01035.py --serve`. Preparation/playback CLI: `run_welding_sample.py --sample ID --prediction --prediction-root ROOT --layout stp`; `--prepare-only` separates native math from Isaac. Renderer also accepts `--solution`, `--output`, `--capture-dir`, `--duration-sec`, `--headless`, `--auto-close` and `--no-video`. All direct paths in this audit were operator/backend owned, not browser input.

| Contract | simulator_final | Comparison |
|---|---|---|
| original H5 XYZ / RPY | mm / degrees; N×3 or N×6 | native STP convention identical |
| OBJ vertices | mm → meter once in native scene builder | same source functions |
| prediction input | trajectory.npz: predicted_path_m, ground_truth_path_m; finite N×3 | original NPZ byte-copied; no correction |
| metadata | episode_id/sample_id; source frame; source_units=mm; scale_to_meters=.001 | same required fields, final adds dataset/source-frame alias |
| XYZ order / axes | XYZ, z-up, rigid rotation det=+1 | no swap/sign/extra scale found |
| prediction placement | predicted @ native rotation.T + translation | same GT-derived scene placement, no prediction-start alignment or snapping |
| robot base | native URDF importer fix_base=True, distance_scale=1.0 | current web renderer manually authors URDF visual FK instead |
| table/environment | native STP reference layout; center [.860,0], top=-.010, floor=-.670 m | same native placement source; web used separate rendering helper |
| tool/TCP | mounted_cad_transform; CAD rear [0,0,-8.4] mm; real CAD tip offset | native tool source and robot URDF byte-identical |
| orientation | native fixture reference, model predicts XYZ only; T_RR native exterior policy | no VLA orientation output used |
| interpolation / IK | native <=5 mm / 3 degrees, original corners, solve_mounted_path / FK | same core files; no new algorithm |
| renderer | native add_workpiece, mounted torch, Articulation targets + positions, zero gravity timeline | web renderer was kinematic FK visual without native importer |
| red path | native measured tool-tip sweep; green planned path = comparison only | proposed native prediction line must be bound to original prediction, not planned_tcp |
| camera | native GT seam center + native saved offset, distance scale 1 | previous web camera used its own overview and capture pose |
| default layout | stp | older STP CLI defaults legacy but web passed stp explicitly |

No confirmed double mm→m, XYZ swap, repeated H5 start, repeated TCP offset or duplicated source_to_scene was found in the inspected Strict path. Source files `welding_scene_layout.py`, `welding_contact_fixture.py`, `welding_environment.py`, `welding_tool_geometry.py`, `prepare_rb5_h5_trajectory.py` and RB10 URDF are byte-identical between final and STP. final adds rough.json stage support, model export discovery, revised camera/video handling and native command options. These differences do not justify copying web transforms into final.

### Actual standalone smoke

Original included rb10/rb5 solution files do not contain mounted_fixture_v2 and cannot pass the current native tracking check. Historical queue successes were present, but their Linux output paths/original exports were not available in this Windows copy. Therefore the available existing B_PR_03_0004 Guided artifact `7bdec2fd-a3dc-478e-b623-ca8ae448f44d` was supplied in the native NPZ/metadata contract. This was an independent standalone fixture test, not a replacement for the user's selected current job. No model was called.

URDF import may generate files beside assets, so native Python/source/assets were byte-identically copied into the owned audit snapshot. Native CLI/geometry/IK/renderer functions were not patched or replaced. Snapshot/hash manifest and every generated file are under `.cache/simulator-final-audit/71f050c6-1b58-452f-bb7d-aa569c17408b/`. Ownership uses the existing launch gate, kill-on-close Job Object and runtime lease. Two harness setup errors (busy completed web preview, incorrect lease context-manager use) occurred before any native launch; they were corrected without launching Isaac. There is only one actual standalone SimulationApp launch and no native retry.

Native preparation succeeded: 9 source points → 18 playback points; maximum interpolated tool-tip error 0.004435 mm, mount gap 0 mm. H5/OBJ resolution used the exact B_PR_03_0004 dataset folders. Native `prediction_targets` replaces every target XYZ with predicted XYZ; H5 supplies placement/orientation metadata and comparison GT. `planned_tcp_xyz_world_m` is comparison/marking input, not the native robot position target.

At Isaac 6.1.0 startup, native renderer failed at line 425–432:

```text
Can't execute command: "URDFCreateImportConfig", it wasn't registered or ambigious.
RuntimeError: URDFCreateImportConfig failed
```

Installed `isaacsim.asset.importer.urdf` version 3.11.10 exports URDFImporter / URDFImporterConfig. Its source does not register URDFCreateImportConfig / URDFParseAndImportFile; its extension startup only stores ext_id. Merely identifying that the importer directory exists does not establish compatibility with the native legacy Kit commands. Installed extension/source/settings were read-only and unchanged.

The native child and CLI returned exit=0 after traceback/shutdown. There was no scene.usda, video, successful playback or web capture. Exit=0 was recorded as process evidence, not treated as success. `diagnosis.json` records standalone_pass=false / SIMULATOR_FINAL_NATIVE_URDF_COMMAND_UNAVAILABLE. No adapter live smoke was attempted. Owned process/job/lease cleanup completed.

### Coordinate/environment evidence

| Preparation runtime | source/H5 identity | workpiece/table/CAD pose vs old STP | source_to_scene / tool reference / joints |
|---|---|---|---|
| py3_12: Python 3.12.3, NumPy 1.26.4, SciPy 1.16.0, trimesh 5.1.0 | exact | exact | all arrays exact; predicted-world difference 0 mm |
| Isaac Python: Python 3.12.13, NumPy 2.3.1, SciPy 1.17.0, trimesh 5.1.0 | exact | workpiece max difference 1.11e-16 m; table/CAD exact | relative rigid rotation 180 degrees; predicted-world max difference 101.845489 mm |

Both use the same native final code and same source data. Native contact registration selected a different rigid placement under the second environment; it was not an adapter-applied extra transform. The precise numerical cause within native contact extraction/ICP remains unproven. No native registration or orientation policy was changed to conceal this difference. `comparison.json` retains field-by-field differences and source identity.

### Requested integration status

1. Standalone entrypoint: audited; native playback failed before URDF import.
2. Original coordinate/frame contract: established from source as above.
3. STP differences: native core placement files match; renderer/articulation/camera differ from web.
4. Coordinate bug: no double conversion proven; runtime-dependent 180-degree placement difference observed.
5. New adapter: deliberately not implemented after standalone failure, as requested.
6. External source/config modifications: none; hash check passed.
7. Prediction/native input: original 9-point NPZ byte-copy; no alignment/scaling/start replacement.
8. H5/OBJ resolver: original exact sample-directory/native teaching→modeling sibling mapping passed.
9. GT: metadata/placement/orientation/comparison only; no GT robot target substitution.
10. Playback source: native solved targets derive from prediction; actual movement was not reached.
11. Actual Isaac: 1 standalone launch, FAIL; 0 integration launches.
12. Web live: not implemented/verified for final; existing STP UI retained.
13. Selector/.env: unchanged dataset_stp; no dataset_final switch before prerequisite PASS.
14. Rollback: existing dataset_stp is retained and still active.
15. Focused verification: native prepare-only under both runtimes, identical source hashes, array/transform comparison and installed importer source audit. No integration pytest/build was run because no integration code was changed and the explicit stop condition applied.

Required next prerequisite: establish a runtime providing the two legacy native URDF Kit commands, or separately approve/audit a backend-owned runtime compatibility bridge preserving the native importer settings/articulation behavior. Re-test standalone before implementing the prediction adapter. Neither an importer installation/version change nor a new compatibility layer was performed in this audit.

A=NO; B=NOT_IMPLEMENTED; C=YES (no extra transform added); D=UNVERIFIED; E=UNVERIFIED; F=YES (offline native target lineage only); G=NO; H=NO; I=YES.
