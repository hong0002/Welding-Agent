# Simulator live view, linear VLA path and compact Assistant

The owned renderer remains `backend/current_vla_isaac_preview.py`. The sibling
`simulator_stp` and installed Isaac sources/assets are read-only. Root `.env`,
VLA source XYZ, approval lineage, scene transforms, native IK/playback, simulator
admission and physical execution policy are unchanged. Physical execution remains
disabled; `physical_robot_executable=false`, `vla_orientation=false`.

## Live transport

Dataset STP/v2 Robot Preview creates an optional `LiveFrameProducer` from the
current Kit update loop. Installed Kit `capture_viewport_to_buffer` returns an
RGBA8 viewport buffer; the owned adapter copies the callback capsule and encodes
JPEG (quality 80, maximum 1280×720, target 8 FPS). It never captures the Windows
desktop. The callback handle stays alive until completion. One in-flight capture
and one atomic `outputs/<request UUID>/live/latest.jpg` + `status.json` pair bound
memory/disk usage. Stalled capture never blocks or queues more GPU callbacks.
Playback updates/IK/export remain authoritative and retain their original errors.
Viewport, Pillow, callback or optional frame write errors skip frames, use safe
warning codes and never set simulator FAILED. Live availability is separate from
playback success and the existing P0/P4/P8/path_detail capture results.
The installed Kit 2.1.0 viewport utility and ByteCapture callback signature were
read directly; its bundled `omni.kit.pip_archive` contains Pillow. No installed
module, external simulator source or asset was modified or launched for this audit.

`GET /api/simulator/current-preview/frames?job_id=<UUID>&artifact_id=<UUID>` keeps
its existing static capture gallery and adds `live` availability, LIVE/CONNECTING/
PAUSED/OFFLINE, measured FPS, target FPS and a bound relative URL. React polls this
small status/gallery at its existing three-second interval, not at frame rate.
The browser decodes MJPEG without per-frame React state or whole-page polling.

`GET /api/simulator/current-preview/live/<session UUID>/<request UUID>` requires
job/artifact UUID queries and optionally accepts a connection UUID for an explicit
browser reconnect. Connection identity confers no permissions. This read-only
route returns `multipart/x-mixed-replace; boundary=frame`, no-store and nosniff.
Unapproved cross-site Origin/fetch requests and arbitrary parameters are rejected.
The existing full proof checker, exact active job/artifact/package/kind and owned
session/request boundaries are rechecked before frames. Locks are released before
yielding bytes or waiting for clients. Changed source approval, Stop, FAILED,
completed playback, new request/job or disconnected clients terminate the stream.
Older JPEGs are never reused across requests. Files with different identity,
changed hash, invalid JPEG, stale timestamps or unsafe resolution are skipped.

Robot Preview selects live by default when available. Static capture tabs and
capture enlargement remain available. Explicit reconnect uses a fresh browser
connection UUID to avoid reuse of a completed multipart image. Stream errors use
the available static capture and show a viewer warning without changing playback.
During temporary frame loss, PAUSED and the last good in-session image may remain;
Stop/new job removes both live and static images. Successful playback ends live
production, retains existing captures and shows PAUSED/latest capture. Path Preview
retains static capture; it does not claim robot motion or a robot live stream.

## Path display

Both Path and Robot Preview call the same `define_polyline` helper. Dataset STP
uses one red `UsdGeom.BasisCurves`: linear, nonperiodic, `curveVertexCounts=[N]`,
width 0.006 m with **constant widths interpolation**. All original source points,
their order and adjacent duplicates are preserved through the existing audited
source-to-scene display transform. There is no source resampling, smoothing,
correction or fitting. STP point markers are OFF; green GT/reference remains.
The native derived robot playback is unchanged. The generic renderer handles
2/9/N points, one-point Sphere fallback and nonfinite input without geometry
correction. Dataset v2/legacy color and marker policy remain unchanged.

## Inspector

`ModelDetails` is a native keyboard-accessible details/summary accordion, closed
by default and reset only on a new job. Segment validation/approval/raw warnings
and YOLO current view/count/unavailable remain visible in its header. Expanding
reveals all previous output, warning, raw-edit, confidence and reuse controls.
It never forcibly reopens after the user closes it. An independently scrollable
detail body caps the space taken from Assistant. Assistant fills the remaining
Inspector body; compact spacing/two-row resizable composer and a scrolling
transcript reserve usable input space. Small screens retain reachable controls.
Plan/simulator tabs, Agent transport/origin and manual debug remain unchanged.

## Existing immutable renderer descriptors

Owned renderer fingerprints include the new producer. Old descriptors are never
silently updated by status polling, and source packages/proofs are never rewritten.
For a cached descriptor from either exact allowlisted pre-UX or pre-live release,
the explicit offline descriptor-only command is:

```powershell
cd "D:\Research_and_Paper\2026경남AISW경진대회\code\Welding-Agent"
.\.venv\Scripts\python.exe -m backend.refresh_preview_ux --artifact-id <current-artifact-UUID> --backend dataset_stp --kind both
```

This verifies every original source, approval, asset and native playback hash,
creates a new descriptor UUID, preserves the original descriptor and package and
updates only readiness's descriptor reference. Unknown renderer releases or
changed evidence are refused. It performs no model call, native recompute or
Isaac launch. If only one preview kind was prepared, refresh that kind separately.

## Manual live verification

Restart the backend and run frontend `npm.cmd run dev`. Select the current dataset
job and its approved mask/guidance/VLA artifact (reuse existing artifacts where
available). Refresh its known cached renderer descriptor if needed. Open
Simulation → Path Preview → confirm the continuous red line → Robot Preview
(perform the explicit offline robot preflight if it has never been prepared).
The owned renderer starts Isaac; do not start legacy sample replay in parallel.
While robot poses play, inspect the web LIVE viewport; switch P0/P4/P8/path detail,
return to Live, then Stop and verify images/LIVE disappear. Check source point
count=9, immutable source hashes, `vla_orientation=false` and execution disabled.

**LIVE_SMOKE_PENDING**: this development task uses existing artifacts, fake
viewport/process/HTTP transports and offline tests only. Real GPU viewport FPS,
visibility under the installed renderer and live callback scheduling still need
the operator smoke above. Target FPS is a cap, not a measured performance claim.

## Changed files for this task

- `backend/services/preview_live_producer.py`: optional bounded JPEG producer.
- `backend/services/current_preview_live.py`: bound metadata/JPEG reads.
- `backend/services/current_preview_runtime.py`: read-only live packets and Stop signal.
- `backend/services/current_preview_frames.py`: existing gallery plus live metadata.
- `backend/main.py`: MJPEG route and safe query/origin checks.
- `backend/current_vla_isaac_preview.py`: optional update-loop producer and shared path style.
- `backend/services/preview_visual_style.py`: linear constant-width curve, STP markers off.
- `backend/services/simulator2_gate.py`: producer fingerprint; strict evidence checks unchanged.
- `backend/refresh_preview_ux.py`: exact pre-live descriptor migration allowlist.
- `frontend/src/components/SimulatorViewport.tsx`, `frontend/src/types.ts`: live/capture viewer.
- `frontend/src/components/ModelDetails.tsx`, `frontend/src/components/AssistantPanel.tsx`,
  `frontend/src/App.tsx`, `frontend/src/styles.css`: accordion and flex chat layout.
- `tests/test_preview_live.py`: producer, ownership, Stop, failures and renderer tests.
- `frontend/e2e/simulator-live.spec.ts`, `frontend/e2e/assistant-layout.spec.ts`,
  `frontend/e2e/model-display.spec.ts`: fake live/UI regression and raw-edit accordion.
- `README.md`, `docs/architecture.md`, this document: contracts/operator steps.

Rollback: revert only this task's live/renderer/accordion delta, retaining the
pre-existing raw-output-display work, and use the preserved old renderer descriptor
with its matching code. Keep root `.env` and source packages;
never bypass a fingerprint/proof or silently substitute dataset v2/legacy playback.

## Offline verification on 2026-10-02

- Complete fake Playwright regression: **65 passed**. Includes live/capture
  switching, multipart decode/reconnect/error, stale ownership, Stop, default
  collapsed model details, FAIL/approval/YOLO summary, raw edit buttons and
  reachable Assistant input at 1366×768/390×844. No horizontal overflow regressions.
- Complete pytest run at that point: **701 passed**, one temporary-file
  `os.replace` hit host Windows `WinError 5`. That exact dummy vertical-region
  test immediately passed alone in a fresh isolated directory. No storage
  semantics were changed to mask filesystem intermittency.
- Final live/renderer and existing capture regression after the descriptor
  migration/publication-race additions: **30 passed** (18 new live/renderer
  cases, 12 existing capture cases). Checks named viewport capsule copying,
  2/9/N/duplicate/single/nonfinite curves, exact source preservation, strict
  UUID/proof/origin binding, Stop/changed approval/new request, optional failures
  and descriptor-only migration with original bytes/proofs preserved.
- Final frontend TypeScript/Vite build, backend compileall and diff whitespace
  checks passed. Vite retains its existing bundle-size warning.
- Segment2, Trajectory3, YOLO, Guided VLA, OpenAI, SSH retrieval, Simulator and
  Isaac live calls: **0**. **LIVE_SMOKE_PENDING**; no GPU/FPS/GUI live pass claimed.
