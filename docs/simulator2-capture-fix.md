# B_PP_03_0006 capture diagnosis and offline fix

Verdict: **SIMULATOR2_CAPTURE_NONFATAL_FIX_READY**. This records an offline fix,
not a successful live playback after the fix. No Isaac/model/native math was rerun.

## Exact failed attempt

| Field | Value |
|---|---|
| job | d278ed92-0918-4202-aa25-37e7dba5f67b |
| VLA artifact | 6c4cb794-5190-48ad-ad75-c38660b26e5c |
| native prediction package | 2276f847-ca99-4fbd-a516-78eca75c0496 |
| original preview descriptor | 95a65a15-2dcf-4dbf-a0a0-0a081c041236 |
| request | 9950a645-6d1b-4f3f-8e12-ad662ad6aae6 |
| session | 8462cc03-ca3f-412f-a135-7fe0b825404b |
| backend/sample | dataset_v2 / B_PP_03_0006 |
| source/playback | 9 / 9 |

Evidence root (preserved):
`D:/Research_and_Paper/2026경남AISW경진대회/code/Welding-Agent/.cache/simulator/current-previews/sessions/8462cc03-ca3f-412f-a135-7fe0b825404b/`.
Read `native.log`, `kit.log`, `stages.jsonl`, `catalog.json` and
`results/9950a645-6d1b-4f3f-8e12-ad662ad6aae6.json` there.
Result stores RuntimeError/capture_P0 and frames main:289 → capture:95, not a secret payload.
The old source at line 95 raises exactly `Viewport capture incomplete` after its 20s wait.
No screenshot, scene export, final report, or waypoint NPZ was saved for this failed request.

## Timeline and diagnosis

2026-10-01 times below are KST (UTC+9).

| Time | Evidence |
|---|---|
| 23:14:51.773 | owned READY |
| 23:14:51.873–51.875 | job/artifact/package resolved; source float32 finite N9 |
| 23:14:52.042–52.045 | workpiece 24 triangles, predicted N9 curve, GT reference |
| 23:14:52.376 | stored native IK solution loaded/checked; 9 poses, max position error 4.08865e-13 mm |
| 23:14:52.449–52.980 | link0…link6 native DAE visuals created, finite=true |
| 23:14:52.985 | tool visual loaded |
| 23:14:53.628 | **last successful stage: waypoint_completed P0**, FK applied, tip residual 0.0000202328 mm |
| 23:14:53 | Kit task exception: Unicode → multibyte codepage mapping failed |
| 23:15:13.956 | RuntimeError at capture_P0, failed result; P1…P8 never reached |

The log line is CP949 bytes; decoding as UTF-8 obscures the error. Correct text:
“대상 멀티바이트 코드페이지에 유니코드 문자의 매핑이 없습니다.”
The failed output path passed to `capture_viewport_to_file` contains Korean directory names.
Confirmed: **B Unicode/codepage failure during capture + A incomplete viewport capture
after the file wait**. No evidence of a viewport-not-ready error or IK failure.
The internal offending conversion argument is not named by Kit; the full capture path
is the known non-ASCII boundary. ASCII staging success still needs a separate live check.

Prior B_PR_03_0001 session `0beaee41-0c6c-4e68-beef-95e22beb8d86` has the identical
CP949 error at 14:36:26 KST and capture_P0 failure 20s later. Same confirmed error pattern.
All exact H5/OBJ/source/job/approval/native hashes passed the normal admission gate before
editing. Native offline IK passed; actual Isaac FK is proven only at P0, not full playback.

## Changed policy and fatal boundary

For **dataset_v2 only**, P0/P4/P8/detail capture is optional. Each is attempted once.
Missing/zero-byte/incomplete files, viewport exceptions and copy errors produce safe
CAPTURE_WARNING codes. Continue original native pose order; no new interpolation,
alignment, trajectory, IK, GT target or orientation is generated.
`playback_status=SUCCEEDED` may coexist with `capture_status=PARTIAL_FAILED` or `FAILED`.
Runtime reports status SUCCEEDED and reason SIMULATOR2_CAPTURE_WARNING, retains READY,
process and lease until normal Stop. Captures successfully saved are listed truthfully.

Viewport API receives `tempfile.mkdtemp(prefix='weld_preview_')/P*.png`, with the entire
resolved path checked as ASCII. On this Windows installation the temp root is ASCII.
Non-ASCII temp roots are refused with CAPTURE_ASCII_PATH_UNAVAILABLE. Python shutil copies
successful files into the Korean owned evidence path; Kit never receives that destination.
Staging is unique per request and retained as diagnostic evidence (no unrelated cleanup).

Scene/robot creation, app.update, FK residual and mandatory scene/waypoint/report export
failures remain fatal. The optional catch encloses viewport request and file operations
only; it cannot absorb scene update exceptions. Backend validates the full native count,
source/GT equality, exact native targets/parameters and measured finite FK residual <=1mm.
Legacy current preview and existing replay keep their completion and capture requirements.

## Offline verification and preserved evidence

`tests/test_preview_capture.py` exercises capture success, P0 timeout, P4 API failure,
all failed captures, zero/incomplete files, ASCII isolation, core-update fatal errors,
READY/lease persistence until Stop, FK/visual/scene fatal cleanup, incomplete results,
XYZ mutation rejection and immutable descriptor refresh/rejection. All use fake callbacks,
native output fixtures and fake processes. Playwright covers separate capture/playback
status and rejection of arbitrary path text in warning codes; existing replay regressions run.

Final verification: **497 pytest passed**, **34 Playwright E2E passed**, frontend build,
compileall and diff check PASS. The new capture module has 21 focused fake tests.
An initial full pytest had one WinError 5 on unrelated temp-file replacement; an elevated
attempt could not enumerate the sandbox-owned temp root. A fresh ASCII basetemp under
CreatorTemp completed all 497 tests normally, without changing storage implementation.
Playwright uses the explicit fake backend/Runner and installed Chrome, never real models.

Protected hashes are recorded under `.cache/simulator2/capture-fix-audit/`. Original source
trajectory, approved mask, job, prediction package and stored native solution remain unchanged.
Existing logs/results and previous descriptors remain unchanged.

For this artifact the offline rebind was completed: new preview descriptor
`8dbbcd77-b21f-407c-88ed-04f2dcaf8168`, same package
`2276f847-ca99-4fbd-a516-78eca75c0496`, source9/playback9. `after.json` confirms all
seven protected file hashes unchanged and normal admission PASS. Native recomputation
and Isaac/model calls are zero. The command below is idempotent for this new descriptor.

## Next explicit manual GUI check

Owned renderer changes stale the old readiness descriptor. To reuse this exact native
package without repeating IK, use the explicit offline operation:

```powershell
.\.venv\Scripts\python.exe -m backend.refresh_capture_descriptor --artifact-id 6c4cb794-5190-48ad-ad75-c38660b26e5c
```

This accepts only the audited prior code fingerprint, verifies current job/approval/source
and every native/external asset hash, and writes a **new descriptor UUID** with the same
package. It does not update the old descriptor/package or call native math/Isaac/models.
Unrelated stale releases or changed input must be rejected, not silently rebound.

The current artifact is already rebound. After backend restart, refresh the existing job in the browser.
Click Robot Preview only as a separate user action. Expected: P0…P8 and final pose;
capture failure warnings may appear while playback completes and GUI remains open.
Stop must still cancel only the owned process. Full live playback/capture success remains
unverified until that manual action; no automatic live retry is performed by this fix.
