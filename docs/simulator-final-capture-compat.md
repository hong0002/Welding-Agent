# Native simulator_final capture transport — 2026-10-06

**PARTIAL** — native capture and playback completed; the requested completely
traceback-free startup condition is not met by the installed Isaac sensor extensions.

## Capture audit and fix

The original `capture_frame()` requested `get_active_viewport()`, set 1280×960,
performed 40 native updates, then called `capture_viewport_to_file()` directly
with a PNG destination under the Unicode Welding-Agent project path. The parent
directory existed. It retained the capture object but only polled file presence
for 20 seconds. The previous headless session reached articulation and tool
verification; the viewport was available. A renderer task exception preceded a
missing start.png and the deadline error.

Installed `omni.kit.viewport.utility` 2.1.0 returns a future-like capture delegate.
`Capture.wait_for_result()` waits for the capture delegate's future. Its
`MultiAOVFileCapture` schedules a separate renderer file-writing task; future
completion alone does not prove file completion. SDK tests separately synchronize
file writing. The original C++ task exception did not propagate through native
Python and its text was lost in the mixed-codepage stdout decoding.

`backend/viewport_capture_compat.py`, copied unchanged beside the authoritative
native renderer, replaces only image transport:

1. Preserve the existing viewport, resolution and 40-update warm-up.
2. Submit exactly one file capture to a unique ASCII `weld_capture_*` temporary
   directory. Do not retry or replace the scene/camera.
3. Observe `wait_for_result(completion_frames=0)` while driving native updates.
4. Require complete native RGB8/RGBA8 PNG chunks/CRCs and decompressed scanlines.
5. Python copies to the original Unicode destination with atomic replacement.
6. Remove only the helper's own verified temporary directory.

Mandatory capture errors propagate. Reason codes distinguish VIEWPORT_NOT_FOUND,
CAPTURE_TASK_EXCEPTION, CAPTURE_TIMEOUT, CAPTURE_FILE_NOT_WRITTEN,
CAPTURE_DECODE_ERROR, CAPTURE_COPY_FAILED and CAPTURE_ASCII_PATH_UNAVAILABLE.
Python task/API exception class/message is preserved in ASCII-escaped JSON stdout
and `capture.diagnostics.jsonl`. Logging failures cannot replace the primary
capture failure. C++ background writer exceptions still originate in Kit logs;
they are not falsely described as Python future exceptions.

The single new native run succeeded at every capture using an ASCII SDK path and
Python Unicode copy. With the same scene/camera/headless/PNG policy, the direct
Unicode file-writer compatibility boundary is the supported cause classification.
The exact C++ encoder/conversion exception from the old run remains unavailable.
No ASCII alias of the dataset/project was made and no dataset was moved.

## Single standalone execution

Attempt: `41dd5a15-1765-4d8f-9f79-6af044ab891c`.
Evidence root: `.cache/simulator-final-audit/<attempt>/`.
The old URDF/capture attempts remain untouched. One new SimulationApp instance;
no automatic retry and no model calls.

| Requirement | Evidence |
|---|---|
| B_PR_03_0004 existing Guided source | Original byte-copied trajectory.npz, SHA256 80d07b71d0c01e18e9cf9a40910c4fad0c11c3bc74493e8a7a6f81425660ca1d |
| Preparation | Original native prepare(), 9 source → 18 playback points; tip error 0.004435 mm, flange gap 0 |
| URDF / articulation | Isaac 6.1 API import; native six joints and TCP initialized |
| Start capture | 1280×960 PNG, 503055 bytes, valid decode |
| Middle capture | 1280×960 PNG, 519608 bytes, valid decode |
| End capture | 1280×960 PNG, 588812 bytes, valid decode |
| Native playback | `[PLAYBACK] finished`; start/end max joint change 0.09596702563922 rad |
| Tool attachment / actual endpoint | End mount gap 0 mm, tip error 0.000330 mm |
| Native scene/result | scene.usda and scene.actual_weld.npz saved; 373 measured points, 1780 painted triangles |
| Cleanup | Process exited 0; owned Job Object closed and lease released |

Start/middle/end images were visually inspected. Native STP table, exact
workpiece, RB10 and ATU01035 are visible; robot/tool pose changes between images.
The native camera clips part of the robot base/left side; camera was not altered.
Red remains native measured torch-tip sweep/paint (GT reference is green).
The red trace is small in the original overview but is present in the final
native scene and capture. No red-style/scene change was folded into this fix.

Read-only pxr/NumPy post-inspection created zero SimulationApp instances.
Original NPZ prediction equals native `predicted_source_xyz_m` exactly.
Native target XYZ derives from those predictions through unchanged source_to_scene.
Every prepared array equals the preceding Isaac preparation. The actual saved
red BasisCurves points exactly equal the recorded 373 measured points at USD
float32 precision. Measured start/end span is 66.17704077431303 mm.
`diagnosis.json` records these links; `result.json` retains the original supervisor
result, which is FAIL because it requires the absence of every traceback.

## Remaining explicit prerequisite

The capture/playback application path has no traceback. However, startup logs
contain separate pre-existing Isaac extension failures:

```
ImportError: cannot import name 'SUPPORTED_LIDAR_CONFIGS'
           from 'isaacsim.sensors.experimental.rtx'
KeyError: 'isaacsim.sensors.rtx'
```

These occurred before scene construction and were also present in the previous
capture-failing attempt. They did not stop this native playback, but they do not
satisfy the user's explicit “traceback 없음” criterion. They are not hidden,
ignored in the final verdict or repaired by editing D:/isaacsim. A separate
runtime extension/startup compatibility change and another specifically
authorized standalone run are needed to establish a clean startup.

Accordingly SimulatorFinalClient, dataset_final selector, `.env` switch and web
live smoke remain deferred until full standalone PASS. The current dataset_stp
backend remains untouched and available. No coordinate/registration/orientation,
camera/renderer composition, IK/FK/interpolation/playback-time or 180-degree
placement adjustment was made. GT is not the playback target. Simulator-only
orientation is retained; physical_robot_executable=false.

## Changes, tests and rollback

New files: backend/viewport_capture_compat.py,
backend/apply_simulator_final_capture_compat.py,
tests/test_viewport_capture_compat.py and this report. README/architecture point
to the current evidence. External changes: capture_frame block only in
run_rb10_trajectory_with_ATU01035.py, plus viewport_capture_compat.py. The rest of
that renderer is byte-identical to its post-URDF-compatibility version.

Focused fake/offline tests: 18 passed (12 capture + 6 URDF). Compileall and
frontend build passed. No full pytest, web integration or model calls. The final
helper's additional diagnostic-directory error handling was tested offline;
it adds no successful-path render/capture behavior and did not trigger a rerun.

Backup: `.cache/simulator-final-audit/capture-compat-source-backup/`. Restoring its
renderer and removing the external viewport helper rolls back this capture-only
change while retaining the previous URDF fix. Dataset_stp rollback requires no
environment change because it remains selected.

A=YES; B=YES; C=YES; D=YES; E=YES; F=YES;
G=DEFERRED_UNTIL_FULL_STANDALONE_PASS; H=YES.
