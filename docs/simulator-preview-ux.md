# Current Web VLA simulator UX

2026-10-02: `SIMULATOR_STP_UX_OFFLINE_PASS_LIVE_PENDING`.
No Segment2/Trajectory3/Guided VLA/OpenAI/SSH/native math/Isaac live calls in this work.
External simulator_stp/simulator2/Isaac and root `.env` are unchanged.

## User flow

Dataset sample → Segment2 → human F mask approval → Trajectory3 2D guidance →
Guided VLA original 9 XYZ → current immutable prediction → Simulator.
Top navigation: PREPARE Scene / Mask / Instruction, PLAN Rough / VLA ready,
PREVIEW Simulator. Validate navigation is removed; backend validation/routes remain.

1. **현재 VLA 경로 보기 · Path Preview**: exact sample scene and source XYZ, no robot motion.
2. If Robot Pending, **로봇 준비 확인 · Offline**: explicit native IK/FK/preflight only,
   no model/Isaac. If already ready, skip this button.
3. **VLA 로봇 미리보기 · Robot Preview**: native derived playback with simulator policy
   orientation. VLA supplies XYZ, not orientation.
4. **시뮬레이터 중지** when finished. Only owned processes are stopped.

Current-state recommendation is highlighted; missing VLA/config/assets/native readiness
has an explanation. No action is dispatched by navigation or status/frame polling.
Dataset backends hide old sample replay/profile entirely; legacy backend retains those
strict APIs behind a closed advanced item. Unrelated replay sample IDs do not appear in
the current artifact card.

YOLO = object detection display; Segment = binary 2D mask; Trajectory3/Rough =
2D guidance; Guided VLA = original 3D prediction; Simulator = Path/Robot Preview.

## Red source path

`backend/current_vla_isaac_preview.py` draws `/VLA_PREDICTED_9` using
`backend/services/preview_visual_style.py`. For dataset_stp, it is one nonperiodic
linear BasisCurves polyline with all nine source points, red RGB (1,.015,.025),
6mm display width, and 1.8mm auxiliary markers. The width is visualization only,
not a welding tolerance. Path and Robot share the renderer. Green GT is reference only;
native derived playback is labeled separately and drives the kinematic robot visual.
No source order/XYZ/ADE/FDE, transform, native IK or interpolation changes.
Dataset v2 and legacy keep their existing orange style.

Always simulation_only=true, physical_robot_executable=false,
fixture_ready=false, validated_simulation=false, vla_orientation=false;
STP orientation_source=simulator_stp_policy. No fallback backend/sample/GT substitution.

## Embedded simulator screen

The inspector shows **시뮬레이터 화면 / Latest capture**, not live video.
Existing owned P0/P4/P8/path_detail viewport images are polled every 3 seconds.
P0/P4/P8 are saved capture milestones, not continuous frames; unavailable images show
a placeholder. Click to enlarge in a keyboard-accessible modal. Path/Robot is labeled.
No screen grab from another application/window and no new Isaac launch is performed.

API (read-only):

| Method | Route | Binding |
|---|---|---|
| GET | `/api/simulator/current-preview/frames?job_id=<UUID>&artifact_id=<UUID>` | Current owned active preview |
| GET | `/api/simulator/current-preview/frames/<sessionUUID>/<requestUUID>/<name>/<sha256>.png?job_id=<UUID>&artifact_id=<UUID>` | Exact listed frame |

Only P0/P4/P8/path_detail names, UUIDs and content digests are accepted. Browser paths
are forbidden. Normal immutable proof revalidation occurs on both reads, including
job/scene/approval/source/native/assets. Session/request must match runtime latest;
RUNNING_PREVIEW/READY with owned process only. A changed proof, wrong identity, old request,
Stop/failure rejects prior URLs. PNGs must resolve inside the owned output, no symlink,
≤8MiB, ≤4096×4096 and ≤16M pixels. Responses use Cache-Control:no-store and nosniff.
Frontend additionally checks metadata/URL identities, drops late poll responses and
hides captures when job/artifact/draft/state changes. Frame errors never rewrite playback
results or bypass admission. This supplies latest screenshots, not an embedded Isaac GUI.

## Operator configuration and existing artifact reuse

Candidate settings only; root `.env` was not changed:

```dotenv
WELD_SIM_BACKEND=dataset_stp
WELD_SIM_STP_ROOT=D:/Research_and_Paper/2026경남AISW경진대회/code/simulator_stp
WELD_SIM_STP_MODE=stp
WELD_SIM_LAUNCHER=D:/isaacsim/python.bat
```

Preserve existing dataset/storage/credentials. Restart Backend after operator settings
changes; during GUI use omit `--reload`. Refresh the web page. Current Preview does not
require legacy replay sample/prediction-root settings.

Renderer fingerprints intentionally invalidate older descriptors. Explicit offline upgrade:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m backend.refresh_preview_ux `
  --artifact-id 6c4cb794-5190-48ad-ad75-c38660b26e5c `
  --backend dataset_stp --kind both
```

This accepts only the exact audited pre-UX release, verifies all source/approval/native
assets with the normal gate, creates fresh immutable descriptor UUIDs, and updates owned
readiness pointers. Old descriptors/packages/native outputs are preserved. Unknown stale
releases or changed evidence are rejected, never repaired by hash substitution or fallback.
No auto-upgrade during polling/preview. The same tool supports the audited dataset_v2
release via `--backend dataset_v2`; otherwise an explicit new native offline preflight is
required for that backend.

The existing B_PP_03_0006 current artifact was upgraded offline: unchanged Path package
c76e3a16-2e91-45f1-999f-9e41af702d9f and Robot package e91e131e-4313-4d86-a9d6-bd82b58adfbd,
source9/playback9, simulator_stp_policy, vla_orientation=false. All 47 protected hashes
(including .env, job/approved mask/source, external native source and old evidence) match.
Evidence: `.cache/simulator-stp/ux-audits/7dbfe85a-28ff-4d38-90db-f0d061898418/report.json`.

## Rollback and remaining smoke

Operator restores the previous explicit `WELD_SIM_BACKEND=dataset_v2` and `WELD_SIM2_ROOT`,
or `legacy` and its prior root/settings, then restarts Backend. Separate caches and strict
replay contract remain. No source dataset/package deletion/conversion is required. Cached
v2 descriptors with an old renderer fingerprint need the explicit audited upgrade above
or a new native offline preflight; do not weaken the gate. To undo this UI/source change,
restore only this change's files from its eventual commit; preserve existing research work.

Remaining live smoke: operator activation, existing artifact Path then Robot, red-line
visibility in Isaac and real viewport capture/API display on installed Kit. No live image
or GUI success is claimed by fake tests. Capture warnings are nonfatal to complete native
playback, but missing scene/FK/core evidence remains fatal. Dataset support is exact sample
admission; missing/invalid H5/OBJ/native preflight is still rejected, not replaced.

## Changed files

- UI: `frontend/src/SimulatorPanel.tsx`, `components/SimulatorViewport.tsx`,
  `components/WorkflowStepper.tsx`, `components/NextAction.tsx`, `components/StatusBadge.tsx`,
  `App.tsx`, `api.ts`, `types.ts`, `styles.css`.
- Backend: `backend/main.py`, `services/current_preview_runtime.py`,
  `services/current_preview_frames.py`, `current_vla_isaac_preview.py`,
  `services/preview_visual_style.py`, `services/simulator2_gate.py`, `refresh_preview_ux.py`.
- Tests: `tests/test_current_preview_frames.py`, `tests/test_preview_ux_upgrade.py`,
  `frontend/e2e/simulator-viewport.spec.ts`, `simulator-stp.spec.ts`, `simulator.spec.ts`,
  `navigation.spec.ts`, `module-integration.spec.ts`.
- Docs: `README.md`, `docs/architecture.md`, `docs/simulator-stp-integration.md`, this file.

Automated tests use injected fake native processes/outputs/transports only. Coverage:
UUID-only buttons, no automatic launch, red connected source9 path, immutable upgrade,
wrong/stale job/artifact/request/session, modified approval/source, content digest,
symlink/non-PNG refusal, Stop/failure clearing, safe API cache headers, Path/Robot captions,
gallery/modal, warning-only capture failures, arbitrary URL rejection, legacy rollback.

Final checks: full pytest **576/576 PASS**, full fake Playwright **52/52 PASS**;
after the final screen-navigation link, its STP/gallery checks **5/5 PASS** again.
Focused backend checks **91/91 PASS**. TypeScript/Vite build, compileall and diff
check PASS. Existing Vite bundle-size warning remains (650kB JS). Screenshot layout
checked with deterministic fake PNGs, not an Isaac live screenshot. Detailed verification:
`verification.json` beside the UX audit above. Protected hashes rechecked after tests.
