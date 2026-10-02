# Dataset Simulator STP: exact OBJ and STP reference layout

2026-10-02: **SIMULATOR_STP_LAYOUT_ROBOT_PREFLIGHT_READY** for the unchanged
B_PP_03_0006 current VLA artifact. **SIMULATOR_STP_LAYOUT_LIVE_SMOKE_PENDING**:
no Isaac/GUI/physics was launched. Root `.env` is unchanged.

The previous exact sample STEP requirement and `SIMULATOR_STP_CONTRACT_BLOCKED`
admission have been removed at the user's request. The old audit remains historical
at `.cache/simulator-stp/audits/c4516838-ad22-414d-bce9-bd5b9ca40073/audit.json`.
The actual contract is exact sample H5 + exact sample OBJ + native `--layout stp`.
The common environment is an STP reference approximation, not sample STEP import
or measured camera/robot calibration.

## Adapter and native boundary

`DatasetSimulatorStpClient` specializes the shared dataset adapter without changing
legacy replay or defaulting/falling back to simulator2. Backend selection is explicit.
`WELD_SIM_STP_ROOT` is the native repository containing `simulator/`.
`WELD_SIM_STP_MODE=stp` maps to the existing native `layout='stp'` parameter / CLI
`--layout stp`; it never invents `--mode stp` or exposes layout/path selection to a browser.

`NativeStpBuilder` uses the fixed audited non-Isaac Python
`C:/Users/hong_/anaconda3/envs/py3_12/python.exe`, fixed internal helper
`backend/simulator_stp_prepare.py`, JSON stdin, `shell=False`, UTF-8,
bytecode disabled, stripped token/key environment, timeout 180s, and no retries.
Only owned `.cache` output is writable; external native sources/config/assets are read only.
The source AST must advertise `--layout stp`, and the audited native files must exist.

Path: exact H5 → `build_scene(exact OBJ)` → native
`apply_environment(..., layout='stp')` → native `prediction_targets` → native
densification. Robot: exact native `ExtractedSamples`/`sample_index` →
`run_welding_sample.prepare(..., layout='stp')` → native orientation/IK/FK,
interpolation and mounted tool policy. No Welding-Agent placement fitting,
projection, target replacement, orientation invention or IK generation is added.

Current job sample = immutable artifact sample = exact H5 stem = exact OBJ stem.
The deterministic dataset path is:
`<dataset>/1.데이터/Other/Other/{로봇티칭데이터,모델링 데이터}/<joint>/<pairing>/<thickness>/<sample>/<sample>.{h5,obj}`.
Missing or mismatched files fail before native dispatch. No recursive dataset discovery.
Exact-H5 GT/frame validation remains native (0.05 mm tolerance). GT is reference only.

Native `source_to_scene` is validated as finite SE(3) and must equal the saved matrix.
The native rigid placement is applied equally to prediction and GT. Native environment
placement centers the workpiece at XY (0.860,0) m, table top -0.010 m, floor -0.670 m.
The renderer consumes saved native environment dimensions (table 0.500×0.800 m),
workpiece vertices, joints, TCP/orientation and tool transforms. It never invokes new
IK for dataset STP/v2. It creates the native reference pedestal/table/legs from those
saved values; it does not load a full environment STEP assembly at runtime.

## Immutable package and renderer

The original `trajectory.npz` is copied byte-for-byte. Source remains N9 float32 XYZ
meters with original ADE/FDE. Derived `SimulatorStpPlaybackTrajectory` is separate:
`derived=true`, `simulator_stp_scene`, mm, native Cartesian linear + orientation SLERP.
Derived count may equal source count (B_PP) or exceed it (other native fixtures).
Source corners/endpoints/order are independently checked; no GT substitution.

Packages use `simulator-stp-current-package-v1`, descriptors
`current-vla-preview-stp-v1`. Source/job/scene/approval, H5/OBJ, native output,
external code/assets and owned helper/renderer hashes are checked before accepting
readiness, before GUI launch and on completion. STP and v2 readiness caches are separate.
Native robot residuals must meet the native diagnostic tolerance (1mm/1deg);
this is not clearance or physical safety evidence.

`orientation_source=simulator_stp_policy`, `vla_orientation=false`.
Always `simulation_only=true`, `fixture_ready=false`,
`validated_simulation=false`, `physical_robot_executable=false`.
No registry or robot execution gate is upgraded by this adapter.

Capture uses the existing ASCII-only temporary staging and nonfatal diagnostics.
P0/P4/P8/detail failures yield `SIMULATOR_STP_CAPTURE_WARNING`; playback continues.
Scene update, robot visual, FK, solution/result-write or incomplete playback failures
remain fatal. Runtime owns its lease/process tree; only Stop/shutdown ends the owned
preview. No real capture or GUI success is claimed by the offline results.

## Web/API

The existing three POSTs accept only job/artifact UUIDs:
`/api/simulator/preview-current-vla/path`, `/api/simulator/preview-current-vla`,
`/api/simulator/current-vla/preview-preflight`. The last performs offline Robot native
math; no Isaac. Status/capabilities are read-only and never run native preparation.
Current preview configuration remains independent of existing sample replay config.

UI shows `Simulator: Dataset Simulator STP`, `Layout: STP Reference Environment`,
`Workpiece CAD: Exact Sample OBJ`, source/derived counts and separate Path/Robot readiness.
Exact STEP Pending labels are removed. Safe STP failure/warning codes are allowlisted;
no browser paths, arrays, native payload or secrets are accepted/exposed.

Simulator development origins are exactly localhost/127.0.0.1 at ports5173 and5174.
Explicit `WELD_CORS_ORIGINS` is authoritative (including empty), with no wildcard
or arbitrary localhost port expansion. Existing sample replay stays independent/strict.

## B_PP offline evidence

Report: `.cache/simulator-stp/audits/50adb163-c3d6-48d1-97f9-37c5dabf4a3f/report.json`.
Path is prepared/admitted first, then native Robot IK/FK once. All model/network/Isaac
calls are zero. There is no automatic retry.

| Check | Result |
|---|---|
| Job | d278ed92-0918-4202-aa25-37e7dba5f67b |
| Artifact | 6c4cb794-5190-48ad-ad75-c38660b26e5c |
| Sample / split | B_PP_03_0006 / train |
| Exact H5 | `Other/Other/로봇티칭데이터/Butt/PP(Plate-Plate)/03(3mm)/B_PP_03_0006/B_PP_03_0006.h5` |
| Exact OBJ | `Other/Other/모델링 데이터/Butt/PP(Plate-Plate)/03(3mm)/B_PP_03_0006/B_PP_03_0006.obj` |
| Path / Robot package | PASS / PASS |
| Source / derived count | 9 / 9, distinct contracts |
| Original NPZ SHA256 | a780879e2a4f63e7f7afdb9396cfc5bdb44eca9ef2e0a73d642162dab34173f8 |
| Original ADE / FDE | 63.03289794921875 / 101.8670425415039 mm, unchanged |
| Native GT/H5 frame error | 0.0000497230443419608 mm |
| Max interpolated tip FK residual | 0.002134256531544596 mm |
| Max interpolated orientation residual | 4.314314275811889e-14 deg |
| Mount/flange gap | 0 mm |
| Max native joint step | 0.30433763253718177 deg |
| Candidate Current/Robot config and cached capabilities | READY / READY (root .env unchanged) |
| Protected source/native/previous files | 33 hashes unchanged, including `.env` |

Path and Robot native SE(3) are identical:

```text
[-0.060676034 -0.066196730  0.995960045  0.492284665]
[-0.994844020  0.085245115 -0.054942206  0.790933312]
[-0.081263735 -0.994158570 -0.071027756 -0.061624178]
[ 0            0            0            1          ]
```

This is native simulation placement, not physical calibration.

## Bounded family coverage

One explicit representative per native family (30 total), scene math only; no whole
dataset scan, inference or family-wide Robot claim. OBJ presence/support and STP scene
readiness are distinct. Other samples require their own identity/frame/native preflight.
29 representative scenes pass. C_PP_03_0001 has 149 nonfinite trajectory values in a
150×6 H5 array; its OBJ parses (16 vertices/24 triangles, finite). Scene admission
rejects that sample with `SIMULATOR_STP_SCENE_BUILD_FAIL`; no fallback sample is used.
Detail: `family-cpp-diagnostic.json` beside the report. H5/OBJ remain unchanged.

| Family | Representative | Exact OBJ | Native STP scene | Robot |
|---|---|---|---|---|
| B_PP | B_PP_03_0001 | PASS | PASS | Not tested |
| B_PR | B_PR_03_0001 | PASS | PASS | Not tested |
| B_PS | B_PS_03_0001 | PASS | PASS | Not tested |
| B_RR | B_RR_03_0001 | PASS | PASS | Not tested |
| B_RS | B_RS_03_0001 | PASS | PASS | Not tested |
| B_SS | B_SS_03_0001 | PASS | PASS | Not tested |
| C_PP | C_PP_03_0001 | PASS | FAIL: nonfinite H5 | Not tested |
| C_PR | C_PR_03_0001 | PASS | PASS | Not tested |
| C_PS | C_PS_03_0001 | PASS | PASS | Not tested |
| C_RR | C_RR_03_0001 | PASS | PASS | Not tested |
| C_RS | C_RS_03_0001 | PASS | PASS | Not tested |
| C_SS | C_SS_03_0001 | PASS | PASS | Not tested |
| E_PP | E_PP_03_0001 | PASS | PASS | Not tested |
| E_PR | E_PR_03_0001 | PASS | PASS | Not tested |
| E_PS | E_PS_03_0001 | PASS | PASS | Not tested |
| E_RR | E_RR_03_0001 | PASS | PASS | Not tested |
| E_RS | E_RS_03_0001 | PASS | PASS | Not tested |
| E_SS | E_SS_03_0001 | PASS | PASS | Not tested |
| L_PP | L_PP_03_0001 | PASS | PASS | Not tested |
| L_PR | L_PR_03_0001 | PASS | PASS | Not tested |
| L_PS | L_PS_12_0001 | PASS | PASS | Not tested |
| L_RR | L_RR_03_0001 | PASS | PASS | Not tested |
| L_RS | L_RS_03_0001 | PASS | PASS | Not tested |
| L_SS | L_SS_03_0001 | PASS | PASS | Not tested |
| T_PP | T_PP_03_0001 | PASS | PASS | Not tested |
| T_PR | T_PR_03_0001 | PASS | PASS | Not tested |
| T_PS | T_PS_12_0001 | PASS | PASS | Not tested |
| T_RR | T_RR_03_0001 | PASS | PASS | Not tested |
| T_RS | T_RS_03_0001 | PASS | PASS | Not tested |
| T_SS | T_SS_12_0001 | PASS | PASS | Not tested |

## Tests and candidate activation

Automated pytest uses fake native processes/output, never external native preparation
or model/Isaac calls. Coverage includes explicit STP selection/layout binding,
exact H5/OBJ, wrong sample rejection, source N9/metrics preservation, separated derived
playback, finite transform, native IK residuals, capture nonfatal behavior, UUID-only
API,5174 origins and v2/legacy regressions. Playwright stubs all preview POSTs and
checks Path/Robot readiness, native labeling and UUID-only bodies. Build includes
TypeScript checks. Final verification: `verification.json` beside the report. STP fake pytest30 PASS;
v2/capture focused42 PASS. Final full pytest556 PASS/1 Windows `os.replace` WinError5
in an existing native-output-preview test; that test reran PASS in a fresh temp root.
An earlier clarification WinError5 also cleared on its29-test targeted rerun.
Full Playwright45 PASS/3 FAIL (existing files, file-access/timing); all three failed
files reran8/8 PASS. STP Playwright passed both standalone and in the full run.
Build, compileall and diff check PASS (existing Vite bundle-size warning only).
The full suites did not finish green in one uninterrupted run; these initial failures
are recorded, not hidden as a clean full-suite pass.

Candidate only: root `.env` was not switched.

```dotenv
WELD_SIM_BACKEND=dataset_stp
WELD_SIM_STP_ROOT=D:/Research_and_Paper/2026경남AISW경진대회/code/simulator_stp
WELD_SIM_STP_MODE=stp
WELD_SIM_LAUNCHER=D:/isaacsim/python.bat
```

Preserve the existing backend dataset/Guided VLA input/storage settings and credentials.
Do not configure replay sample/prediction roots to represent this current artifact.
Rollback: restore the prior explicit `WELD_SIM_BACKEND=dataset_v2` with its unchanged
`WELD_SIM2_ROOT`, or `legacy` for the legacy backend, then restart backend. No packages,
source NPZ, native repository or dataset files need deletion or conversion.

## Manual Isaac smoke (not run)

1. Operator applies the four candidate settings above, restarts Backend, opens the
   existing B_PP job/artifact (no new Segment/Trajectory/VLA run).
2. Check `/api/simulator/status` backend=`dataset_stp`, current-preview and robot
   configuration ready. Capabilities should show separate source9/playback9 readiness.
3. Click **현재 VLA 경로 보기 · Path Preview**. Check exact B_PP OBJ, reference environment,
   orange source9/P0…P8, optional green GT reference, unvalidated/simulation-only labels.
4. Stop the owned preview, then click **VLA 로봇 미리보기**. It must use the verified saved
   native Robot package, not generate renderer IK. Inspect FK/playback evidence and
   sanitized logs. Capture warning is nonfatal; core scene/visual/FK failure is fatal.
5. Stop preview. Confirm owned process/lease cleanup. Do not start existing sample
   replay, physics or robot execution as part of this current-preview smoke.

Offline preparation can be reproduced explicitly with
`.\.venv\Scripts\python.exe -B -X utf8 -m backend.simulator_stp_audit --families`;
it creates new UUID artifacts and reruns native math, but makes no model/GUI calls.
Do not rerun merely to poll readiness; GETs use cached immutable evidence.
