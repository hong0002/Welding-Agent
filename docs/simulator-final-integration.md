# simulator_final: clean standalone, coordinate parity and web integration

2026-10-06 — **SIMULATOR_FINAL_INTEGRATION_READY**

**COORDINATE_ALIGNMENT_FIXED = YES**

This report supersedes the earlier pending verdicts in the URDF/capture reports.
The stages were performed in order: capture/startup compatibility, clean native
standalone, coordinate diagnosis/fix, standalone after the fix, thin web adapter.
No model/API inference, dataset scan, new prediction or physical robot execution
was performed.

## Capture and startup

The native Unicode viewport file-writing boundary failed despite an available
viewport and destination directory. The existing capture helper now submits one
native request to an ASCII temporary directory, validates complete PNG data and
copies atomically to the requested Unicode destination. It preserves the native
camera, viewport resolution and warm-up. The old C++ exception text remains
unavailable; successful ASCII staging establishes a file-writing compatibility
boundary rather than proving a specific codec exception.

An owned Isaac experience copies the installed base/Python app configurations
and excludes precisely the two unused, broken RTX sensor dependencies. The
physics, renderer, viewport and native SimulationApp launch settings remain.
No installed Isaac file was changed and no alternate renderer is selected.

Clean standalone before the coordinate change:
`.cache/simulator-final-audit/e25fdd9d-b8a8-498d-9963-256ac232c481/`.
It returned exit 0 with start/middle/end captures, `[PLAYBACK] finished`, saved
scene and measured-motion NPZ, no traceback, and complete owned cleanup.

## Coordinate root cause

Inputs were identical: B_PR_03_0004 H5, its exact OBJ, original Guided 9-point
prediction, native source and trimesh 5.1.0. The environments were Python
3.12.3 / NumPy 1.26.4 / SciPy 1.16.0 and Isaac Python 3.12.13 / NumPy 2.3.1 /
SciPy 1.17.0. Raw source/OBJ/contact arrays matched.

The contact PCA basis changed signs between NumPy/LAPACK environments. Source
motion is nearly collinear and later ICP correspondences have rank one, leaving
rotation around the tangent unconstrained. SVD then chose different null-space
rolls. Equivalent contact fits were selected by floating-point `<`/enumeration
order, with KD-tree ties adding another ordering dependency. This produced
opposite source-to-scene orientations despite matching workpiece/table placement.
It was not a different prediction, mesh, camera or renderer.

The native registration now uses canonical right-handed PCA hemispheres,
minimum tangent rotation for rank-one updates, native CAD front/up references
for the unconstrained transverse sign, stable equidistant contact ordering and
a deterministic geometric preference only within the numerical cost tie band.
The existing objective still chooses genuinely better fits. No final 180-degree
rotation, scaling, replacement XYZ, prediction alignment or GT playback was added.

Actual installed native preparation was executed offline in both environments
after the fix. Full evidence is in `.cache/simulator-final-coordinate/final/` and
`comparison.json`; the latter retains numeric poses for before and after.

| Comparison | Before | After |
|---|---:|---:|
| source-to-scene relative rotation | 180° | 7.062108168e-10° |
| source-to-scene translation norm | 0.810784114080 m | 7.723244582e-12 m |
| predicted world maximum point difference | 101.845488785 mm | 3.110165959e-10 mm |
| source prediction XYZ maximum difference | 0 | 0 |
| OBJ pose rotation / translation | 0° / 0 m | 0° / 0 m |
| table pose rotation / translation | 0° / 0 m | 0° / 0 m |
| fixed robot base pose | identical | identical |
| initial URDF TCP/tool-world translation norm | 0.044464283289 m | 3.111962271e-13 m |
| contact world XYZ maximum coordinate difference | 0 m | 0 m |
| GT reference XYZ maximum coordinate difference | 0.050695367444 m | 2.220446049e-16 m |
| fixture outward / CAD tool mounting transform | identical | identical |
| inferred weld-TCP reference rotation | 180° | 7.062075525e-10° |

The corrected py3_12 preparation also matches the original successful py3_12
reference: rotation 5.388693831e-9°, translation 5.893318310e-11 m and prediction
maximum difference 2.372584316e-9 mm. Thus the fix retains the original placement.
The base is native fixed URDF link0 at identity; it has no added root transform.
Tool/TCP values are prepared FK transforms, not a second physics run.

## Native playback after the fix

`.cache/simulator-final-audit/69dcd490-7e43-4bab-b8bd-81b307bc24d4/`
is **STANDALONE_PASS**: exit 0, no timeout/traceback, 9 original points → 18 native
playback points, maximum interpolation tip error 0.004191 mm, complete playback,
all three mandatory PNGs, scene.usda and scene.actual_weld.npz, source preservation
and owned cleanup. STP table, exact sample workpiece, RB10, ATU01035 and changing
robot/tool pose were visually inspected in start/middle/end captures. The original
camera clips the left part of the robot and remains unchanged. Native red marks
are the measured torch-tip sweep/paint; green is the GT reference. Red is not
mislabelled as an untransformed source-XYZ polyline.

The original NPZ SHA256 remains
`80d07b71d0c01e18e9cf9a40910c4fad0c11c3bc74493e8a7a6f81425660ca1d`.
Its XYZ equals native predicted_source_xyz_m exactly; raw targets derive from
the same source through source_to_scene. Original model metrics/package bytes
are retained. Native diagnostic metrics remain separate.

## Thin adapter and web evidence

SimulatorFinalClient uses the flat native repository and its original prepare
and renderer entrypoints. It reuses exact sample/job/artifact/approval/selection
and immutable package gates. The renderer executes an owned hash-checked snapshot
using the prepared native solution. It does not rebuild coordinates, scene,
camera, IK/FK, interpolation or orientation. Failed admission never falls back.
An active native window must be stopped before another request.

SimulationApp replaces Python stdout, so completion cannot be intercepted by a
pre-start redirect_stdout wrapper. The backend observes its owned OS pipe's
exact `[PLAYBACK] finished` and matching scene `[SAVE]` markers, then verifies
saved measured endpoints, all PNGs, original prediction, package and approval
before writing an owned observation report. Missing evidence/traceback rejects
completion. Raw native logs remain local and sanitized; public status receives
fixed high-level messages only.

Final actual API smoke:
`.cache/simulator-final-integration/876b1d3e-6b23-421b-ab33-2a031bf575e0/result.json`.
It is **INTEGRATION_PASS**: POST robot-preview returned 202, native READY /
SUCCEEDED, three frame downloads returned 200, source job and prediction hashes
were unchanged, and owned process/lease cleanup completed. One Isaac launch in
this final attempt, model calls 0. Earlier failed attempts are preserved: one
request-contract rejection, one pre-app dependency import failure, one completed
native playback with missed completion observation, and one completed playback
whose PNG route rejected the new native filenames. They were diagnosed and fixed;
there is no automatic retry wrapper.

The embedded viewer polls bound latest captures (start/middle/end), not live
video/MJPEG. URLs require the current job/artifact/session/request/hash. Stop,
upstream edits or selecting another artifact removes stale images. Path-only
inspection uses the original web XYZ viewer; native final Robot Preview includes
both robot and path. Physical execution remains disabled; vla_orientation=false,
orientation_source=simulator_final_policy. This is simulation placement, not
calibrated robot/world registration or collision certification.

## Configuration and use

After integration PASS, only three non-secret root .env entries were changed:

```dotenv
WELD_SIM_BACKEND=dataset_final
WELD_SIM_FINAL_ROOT=D:/Research_and_Paper/2026경남AISW경진대회/code/simulator_final
WELD_SIM_STP_ROOT=D:/Research_and_Paper/2026경남AISW경진대회/code/simulator_stp
```

The STP rollback root had corrupt Unicode and was repaired. Launcher remains
D:/isaacsim/python.bat. Secrets and other configuration entries were preserved.
The already-running backend still reports dataset_stp: it must be restarted in
its original terminal. An unowned user backend process was not killed. Fresh
application configuration reports dataset_final / configured=true.

In the web UI: select the current absolute prediction → inspect source XYZ →
**로봇 준비 확인 · Offline** if readiness is missing → **로봇 시뮬레이션 보기** →
inspect 시작/중간/완료 captures → **시뮬레이터 중지**. Relative raw GPT output is
displayable but cannot silently become native absolute Robot Preview input.

Rollback sets WELD_SIM_BACKEND=dataset_stp and restarts the backend. The original
STP/v2/legacy clients remain intact. Native coordinate rollback restores
`.cache/simulator-final-audit/coordinate-source-backup/welding_contact_fixture.py`
and removes only the added native contact_registration_determinism.py; previous
URDF/capture backups remain independent. No old output/evidence was overwritten.

## Changed files and verification

- Native compatibility/audit: contact_registration_determinism.py,
  apply_simulator_final_coordinate_fix.py, simulator_final_coordinate_audit.py,
  simulator_final_coordinate_report.py, simulator_final_experience.py,
  simulator_final_smoke.py; existing viewport/URDF helpers are retained.
- Thin adapter: services/simulator_final_client.py, simulator_final_contract.py,
  simulator_final_gate.py, simulator_final_result.py, simulator_final_prepare.py,
  simulator_final_preview.py, simulator_final_integration_smoke.py.
- Shared wiring: main.py, current_preview_gate.py, current_preview_frames.py,
  preview_startup.py, simulator2_client.py, simulator2_gate.py,
  visibility_path_preview.py, robot_demo.py. Changes select explicit final
  behavior; previous backends retain their contracts.
- UI: SimulatorPanel.tsx, components/SimulatorViewport.tsx, types.ts;
  frontend/e2e/simulator-viewport.spec.ts.
- Verification/docs: tests/test_simulator_final_client.py,
  tests/test_simulator_final_coordinates.py, safe registration fixture,
  .env.example, README.md, docs/architecture.md and this report.
- External authorized native changes: welding_contact_fixture.py and added
  contact_registration_determinism.py only for this coordinate stage. Prior
  authorized capture/URDF renderer helpers are retained. D:/isaacsim is untouched.

Focused adapter/STP/v2 pytest: 64 passed. Coordinate/capture/URDF: 25 passed using
the existing py3_12 SciPy and pytest from the project environment; no dependency
installation. Fake Playwright/installed Chrome: 5 passed, no native/model calls.
TypeScript/Vite build and compileall pass. The existing 500 kB chunk-size warning
is informational. Full pytest was intentionally not run. Live coverage is one
existing B_PR_03_0004 prediction; it does not establish all-family correctness.

A=YES (capture stage left coordinates/scene/camera intact); B=YES; C=YES;
D=YES; E=YES; F=YES; G=YES; H=YES. Coordinate changes were made afterward,
as explicitly requested, and clean standalone was rechecked before integration.

## Robot button binding follow-up (2026-10-06)

The running backend now confirms dataset_final, robot configured=true, empty
configuration errors, STOPPED and source_point_count=null. The frontend had a
final-only absolute-coordinate disable condition and could select an empty
Final catalog row instead of its renderable Corners/Rough stage. Its generic
disabled fallback then incorrectly described a launcher/assets problem.

The button now counts finite XYZ from the exact selected catalog/display output
and checks the actual runtime robot configuration. No approval, validation,
accepted final, VLA_READY or cached robot_preflight state is required for the
visualization button. Explicit selection is retained; otherwise only current
job/sample geometry is selected, prioritizing Final, Corners, Derived,
Rough/Raw, then Guided. Empty and stale/foreign rows cannot become the default.

Absolute selection still uses the original native STRICT pipeline and binding
gates. Relative/raw selection now explicitly uses DEMO via SimulatorFinalClient,
reusing the owned immutable mapping/FK visualization and original native sample
scene entrypoint. An old successful package supplies a pose seed only; all path
targets derive from the newly selected current XYZ. It does not replace targets
with GT or an old prediction. STRICT failure never switches to DEMO. DEMO is
labelled transformed visualization, not calibrated native absolute playback.

Verification for this change: focused pytest, four fake Playwright/Chrome cases,
TypeScript/Vite build and compileall. Models and Isaac launches: zero. Native
STRICT live evidence above remains historical; the new final DEMO route still
needs a separate user-triggered live check. Root .env and external projects were
not modified in this follow-up. Refresh the web page; restart the backend in its
original terminal if it is not already running with reload.
# B_PR_03_0001 preview-only torch clearance

Only the Welding-Agent-owned preparation helper applies this sample guard;
external simulator_final source/assets and other samples are unchanged.
The B_PR CAD's vertical plate and tube block the native upward torch posture.
The original 33-point GPT2 target also has four points up to 0.526mm inside the
surface; those model points are retained, not repaired or replaced with GT.

For B_PR_03_0001 only, the flange approaches the plate/tube exterior bisector
30 degrees above horizontal. A 10mm virtual weld-tip extension retracts the
physical torch body while retaining every target XYZ exactly. Native mounted
IK/FK is recomputed for this preview-only tool policy. The CAD mount, workpiece,
table, source_to_scene, source NPZ and artifact/approval binding are unchanged.
The uncorrected native solution is preserved in each new owned package.
Package native report/sample_preview_correction records the policy, false
physical execution and false vla_orientation; it is neither DEMO nor calibration.

Current artifact 4a3e566a-8bfe-4510-a449-6ac208515dbf, sample B_PR_03_0001:
source/playback points 33/33, package 1aa1213e-e02e-4a7b-98a5-c1162283a16f.
129 FK samples had zero tool CAD vertices inside the workpiece; nearest tested
near-surface vertex distance was 0.879mm. All seven robot visual-link bounds
were disjoint from the workpiece at the 33 native nodes. These are diagnostic
samples, not continuous collision/dynamics certification.

One actual Robot Preview completed with start/middle/end captures, robot motion
and unchanged prediction source. Session bc4542c4-8528-45ea-bf82-624b03f5e149,
request 827768c4-34f8-4a22-900a-f9700ac4e5c4. No model/SSH call occurred.
Evidence and exact pre-change helper backup: .cache/bpr-preview-clearance.

Rollback: stop the owned preview, restore backend/simulator_final_prepare.py
from .cache/bpr-preview-clearance/simulator_final_prepare.py.before, restart
the backend and explicitly prepare a new current Robot Preview package. Do not
rewrite any old descriptor, prediction or native package. The backup SHA-256
matches the previous audited helper release exactly.
