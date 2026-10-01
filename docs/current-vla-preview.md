# Current web VLA → Isaac diagnostic preview

Current family registry contract: [family-preview-policy.md](family-preview-policy.md).
B_PP now supports exact-asset, neutral source-frame Path Preview; robot/workpiece
placement remains pending. B_PR audited robot restrictions and existing replay gates
are preserved. The B_PR live evidence below is historical and is not a B_PP live pass.

2026-10-01 configuration repair: Current Preview and existing replay have separate
status/admission scopes. Root `.env` already contained the verified
`D:/isaacsim/python.bat`; the previous Simulator loader consulted only process env,
so a backend started without `--env-file` reported the launcher missing.
The loader now reads UTF-8 dotenv directly. Raw status bytes contained correct
Korean Unicode; explicit JSON UTF-8 charset addresses legacy client decoding.
No dataset path aliases, asset modifications or additional Isaac launch were used.
See README for the new status contract. Static configuration readiness does not
change the incomplete live playback result below.

Configuration verification: **CURRENT_VLA_PREVIEW_CONFIGURATION_READY**.
A fresh owned backend on port 18001 returned HTTP 200 with
`current_preview.configured=true`, empty configuration errors, `STOPPED`, null
PID/latest, and the existing `D:/isaacsim/python.bat`. It was stopped after GET-only
checks. Fresh-app response checks also confirmed UTF-8 charset and exact Korean
replay paths. The independent pre-existing port 8000 backend still uses the old
source and requires operator restart; it was not terminated by this repair.
No Segment/Rough/VLA/OpenAI or Isaac launch occurred.

Offline verification: 12 new configuration/admission tests passed; full pytest
returned 416 passed and one Windows `os.replace` access error, whose isolated
rerun passed in a new temporary directory. Full fake E2E: 30 passed. After adding
the previous status-schema UI regression, focused E2E: 4 passed. Final frontend
build, backend compileall and whitespace checks passed. Fake children verified
admission despite missing replay settings, typed 503/409 failures before launch,
UUID-only requests and unchanged strict existing replay rejection.

2026-10-01 latest: **CURRENT_VLA_PREVIEW_CAPTURE_FAIL**.
The separately authorized one-attempt post-repair smoke passed actual DAE loading,
native IK and P0 placement, then failed to capture P0. P1–P8 and the final pose
were not executed. The owned process tree and lease were cleaned up. No retry,
Path fallback or model calls were made. Full preview remains incomplete.

## Post-repair attempt (latest)

| Requested item | Evidence |
|---|---|
| 1. Job | `3fe35636-df6d-46b0-9089-9260ac99ad3e` |
| 2. Current VLA artifact | `4d2134ea-0d91-45aa-b997-42066beceefb`; original live artifact `f2bba528-fb2b-46a6-8c57-d0e1ba10211c` |
| 3. Package | Fresh immutable byte-copy package `0656eb42-bdb4-4783-9584-6894a1f0ac3b`; retained reference `44c5b519-f021-4427-89b9-700c1f277c31` |
| 4. NPZ hash | `73e8e933a50a40a9f47a08494be77736fa94075c7820625e8249f9ccb36a2261`, original/current/reference/admitted copies agree |
| 5. Point count | 9, float32, finite; source prediction and GT arrays compare exactly to the original live artifact |
| 6. Isaac launch/result | Exactly one new GUI launch via the job-ID Robot Preview API, HTTP 202, READY observed, failed at `capture_P0`; owned cleanup complete |
| 7. DAE result | All seven native DAE assets decoded: 80,167 triangles; finite points, DAE/URDF transforms applied and seven USD mesh prims created |
| 8. P0–P8 playback | P0 completed; P1–P8 not attempted because P0 capture failed; native IK solved all nine targets before playback |
| 9. TCP diagnostic | Actual USD tool tip vs P0 target: `0.000020232758426509362 mm`; native IK maximum residual across nine targets: `5.495323605393213e-13 mm` |
| 10. Screenshot | None produced; the requested `P0.png` was not written, and no final pose/stage/waypoint export was reached |
| 11. Fixture | `fixture_ready=false`; registry and validated simulation remain false |
| 12. Physical execution | `physical_robot_executable=false`; no physics stepping |
| 13. Collision warning | `B_PR_TOOL_CLEARANCE_FAIL` remains unchanged; no placement/orientation/path adjustment |
| 14. Existing sample replay | Unused; no external sample/server scripts or Path fallback |
| 15. Verdict | **CURRENT_VLA_PREVIEW_CAPTURE_FAIL** |

Mode remains `CURRENT_VLA_UNVALIDATED_PREVIEW`.
`orientation_source=simulator_fixture_policy`, `vla_orientation=false`.
Original ADE **97.15410614013672 mm** and FDE **155.03475952148438 mm** are unchanged.
Source-frame N9 data is preserved byte-for-byte. Scene targets use only the existing
audited rigid `source_to_scene` convention, one target per source point, shared
with GT reference visualization. There is no resampling, fitting, correction,
interpolation or GT target substitution. Final all-nine stage tracking is **not**
claimed because playback stopped at the first capture.

A fresh smoke backend process loaded the repaired source and existing `.env`.
The existing independent backend/replay configuration was not terminated or
modified. High-level timestamp logging was added before this attempt in the
repository-owned helper/renderer only; it records identities, mesh counts,
waypoint/error diagnostics and capture/result phases, without model payloads,
reasoning, prompts or credentials. Focused offline tests: **18 passed**; compileall
and diff checks passed. No post-failure code repair or live execution was performed.

### Stage timeline

All times below are **2026-10-01 KST (UTC+09)**. JSONL stores UTC timestamps.

| Time | Stage/result |
|---|---|
| 14:35:48.159 | Current job/artifact/reference package preflight; N9/hash/arrays verified |
| 14:35:48.229 | Exactly one `POST /api/simulator/preview-current-vla` sent |
| 14:35:50.234 | HTTP 202; fresh package resolved and owned Isaac process launched |
| 14:36:23.683 | Exact current-session READY signal |
| 14:36:23.781–23.783 | Child rechecks current job, current artifact and exact package/hash |
| 14:36:24.197 | Prediction count/dtype/finiteness checked |
| 14:36:24.451 | B_PR workpiece loaded; `/Workpiece`, 1,252 triangles |
| 14:36:24.454 | `/VLA_PREDICTED_9` created, nine points |
| 14:36:24.457 | `/GT_REFERENCE_ONLY` created; not a target |
| 14:36:24.492–24.766 | Native RB10 URDF/IK started/completed for all nine targets |
| 14:36:24.886–25.724 | `link0.dae` through `link6.dae` decoded, transformed, USD prims created |
| 14:36:25.732 | Actual tool USD reference and single 0.001 CAD scale applied |
| 14:36:26.607 | P0 completed; native link FK transforms and actual USD tip checked |
| 14:36:26 | Kit `carb.tasking.plugin` reports an unhandled task exception |
| 14:36:46.865 | `RuntimeError` at `capture_P0`; failure result written |
| — | P1–P8, final pose, final capture and successful scene/report export not reached |
| 14:36:47.245–47.251 | Cleanup confirmed; no retained owned process or lease |

The safe local exception message is `Viewport capture incomplete`, raised by
`capture()` in `backend/current_vla_isaac_preview.py:95`, called from line 253.
The capture function made 40 updates, requested the viewport capture, then waited
up to 20 seconds for a file larger than 1,000 bytes. No such file appeared.
The corresponding Kit task error, decoded from its CP949 bytes, says:
`대상 멀티바이트 코드페이지에 유니코드 문자의 매핑이 없습니다.`
This is evidence of a Unicode conversion error during the capture phase;
the exact offending path/API boundary is not yet isolated. No capture workaround
was applied and the preview was not relaunched.

Current runtime status uses `robot_motion=false` for an incomplete run; the P0
stage event proves first-pose placement, not successful complete playback.
The native failure result contains only class, phase and source locations.
The failed GUI was cancelled through the owned kill-on-close process tree before
the smoke helper's final stop call. Its final report therefore has
`process_exit_code_after_owned_cleanup=null`; no normal exit=0 is claimed.
Read-only process checks found neither the launched owned PID nor a remaining Kit
process. `source_hashes_preserved=true` covers the original/current/reference
prediction, reference package, current job, native sources/assets and IK helper.
Segment/Rough/trajectory2/Guided VLA/OpenAI/SSH retrieval calls: **0 each**.

Evidence paths (all below this repository):

- `.cache/current-vla-preview-smoke/013168d1-867b-455d-b086-622e6f342120/report.json`
- `.cache/current-vla-preview-smoke/013168d1-867b-455d-b086-622e6f342120/stages.jsonl`
- `.cache/simulator/current-previews/sessions/0beaee41-0c6c-4e68-beef-95e22beb8d86/stages.jsonl`
- `.cache/simulator/current-previews/sessions/0beaee41-0c6c-4e68-beef-95e22beb8d86/native.log`
- `.cache/simulator/current-previews/sessions/0beaee41-0c6c-4e68-beef-95e22beb8d86/kit.log`
- `.cache/simulator/current-previews/sessions/0beaee41-0c6c-4e68-beef-95e22beb8d86/results/b159c925-95fc-42d7-b022-d1ce817596d1.json`

All earlier outputs/packages remain retained. The one-attempt authorization for
this post-repair smoke is consumed; further live attempts require a new user request.

## Previous pre-repair attempt

| Requested item | Evidence |
|---|---|
| Web job | `3fe35636-df6d-46b0-9089-9260ac99ad3e` |
| Current artifact | `4d2134ea-0d91-45aa-b997-42066beceefb` |
| Source live artifact | `f2bba528-fb2b-46a6-8c57-d0e1ba10211c` |
| Admitted simulator package | `44c5b519-f021-4427-89b9-700c1f277c31` |
| Sample / count | `B_PR_03_0001` / 9 |
| Exact XYZ | Current NPZ is byte-identical to the original live NPZ; arrays compare exactly. SHA256 `73e8e933a50a40a9f47a08494be77736fa94075c7820625e8249f9ccb36a2261` |
| Current vs configured replay | Only current job/artifact resolves this action. No `WELD_SIM_SAMPLE_ID`, existing queue or external sample script is used. |
| Isaac mode | `CURRENT_VLA_UNVALIDATED_PREVIEW`, Robot Preview requested |
| Robot motion | **Not completed**: native IK finished, then visual loading failed before P0 playback/capture |
| Fixture ready | `false` |
| Physical execution | `false`; validated simulation and registry validation also `false` |
| Collision warning | `B_PR_TOOL_CLEARANCE_FAIL`; unchanged, no fit/orientation/standoff search |
| Web/API | Enabled “VLA 시뮬레이션 미리보기” and “현재 VLA 경로만 보기”; disabled validated execution |
| Actual smoke | One API POST, one GUI launch, readiness observed, `ValueError` at `robot_visuals`, owned tree/lease cleanup complete |
| Verdict | **INCOMPLETE**, no automatic retry |

The current job/artifact comes from the preceding immutable web artifact replay.
Its prediction and GT were verified equal to the successful live artifact before
submission. This task did not generate a new VLA prediction. Original ADE
97.15410614013672 mm and FDE 155.03475952148438 mm are preserved.

Smoke report:
`.cache/current-vla-preview-smoke/455a8988-5038-4f4c-aeb6-c58c85e73d61/report.json`.
Owned session:
`.cache/simulator/current-previews/sessions/4985f9a7-ab09-4c49-a46f-ec17359ac6e0`.
Request UUID: `b070aa34-0030-4559-8cd2-f9878aa23ca4`.
`native.log` contains READY, current artifact/package/metrics and failure phase.
`results/<request>.json` stores exception class and code locations only.
`kit.log` is redirected into the owned session; credential environment variables
are removed before launch. No raw model request/reasoning/prompt is logged.

The original renderer assumed the URDF **visual** assets were binary STL, but all
seven are static Collada DAE. Collision meshes are separate STL. The failure
occurred after workpiece/path prim construction and before robot poses, stage
export or screenshot evidence. GUI readiness is not proof of completed preview.

## Repair and checks

`preview_mesh.load_visual_mesh` now reads native DAE triangles, source/accessor
strides, interleaved vertex indices, static node matrices, units and active scene.
Materials share source vertices; textures/controllers/animations/unaudited axes
and external resources are not resolved. Matrix serialization follows the
[Khronos COLLADA 1.4 specification](https://www.khronos.org/files/collada_spec_1_4.pdf).
Binary STL is handled separately. No asset is rewritten or downloaded.

Actual seven DAE files / 80,167 triangles passed read-only offline decoding.
The repaired current-job admission validates all seven visual meshes before GUI
launch. An isolated `pxr.Usd/UsdGeom/Gf` check verified the real USDC reference,
the renderer's matrix constructor, native mount transform and one 0.001 scale,
without SimulationApp, omni imports, GUI, physics or another preview attempt.
Reports in the smoke directory:
`dae_offline_audit.json`, `usd_composition_offline.json`,
`post_smoke_source_audit.json` (22 external simulator sources/assets unchanged).

Synthetic tests cover current binding, exact prediction/no GT or old sample
substitution, queue strictness, tampered job/mask/package/source/evidence rejection,
false gates, existing replay compatibility, fake completion, timeout/cleanup,
DAE units/node transforms/indexing and STL decoding. Pytest/Playwright never
launch Isaac or contact model servers.

Final verification: full pytest **337 passed**; final focused preview/mesh suite
**18 passed** after launch cleanup hardening; Playwright **25 passed**; frontend
production build, backend compileall and diff checks passed. One earlier existing
Agent test failed intermittently during the full suite, then passed individually
and in the final full run; no Agent implementation was changed for that failure.
The build's existing bundle-size advisory remains.

## Usage and limits

Backend receives only one UUID identity:

```json
{"job_id":"<current VLA_READY job UUID>"}
```

- Robot: `POST /api/simulator/preview-current-vla`
- Path only: `POST /api/simulator/preview-current-vla/path`
- Status/logs: existing GET routes, with `current_preview` status appended
- Stop: existing `POST /api/simulator/stop`, cleans owned current/legacy runtime

The backend owns the artifact proof, paths, immutable package, audit transform,
queue catalog and fixed renderer. Optional artifact UUID input resolves the
current job proof when present, so edits cannot bypass invalidation. Archived
completed live artifacts retain the original approval/source checks.

Diagnostic placement is currently limited to the audited B_PR sample's exact
H5/OBJ hashes. Unsupported samples fail admission; they never use another sample's
fixture. The -X candidate and fixed initial flange orientation are visualization
conventions, not calibrated or clearance-approved policies:
`orientation_source=simulator_fixture_policy`, `vla_orientation=false`.

Robot Preview uses native URDF IK/FK and visual meshes, not a physics articulation
or welding executor. It shows only the nine unchanged targets sequentially,
without forced interpolation. Orange XYZ is prediction; green GT is reference
only. Actual stage-tip residual is diagnostic (native 2 mm stage check), not a
new physical clearance threshold. The known penetration warning stays visible.
Path Preview is an explicit debug option; failures never automatically retry it.

The operator smoke helper uses the same job-ID API and no model calls:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m backend.current_vla_preview_smoke --live
```

The latest separately authorized execution is recorded above. Do not invoke the
helper again under this attempt's authorization: its one-attempt allowance is
consumed. Existing failed sessions, packages, successful VLA/Segment/Rough artifacts
and clearance results are retained.


Dataset Simulator v2 is an explicit current-preview backend (`WELD_SIM_BACKEND=dataset_v2`), default/rollback legacy.
`DatasetSimulatorV2Client` reuses native scene/prediction/interpolation/robot preparation through a fixed offline bridge.
Source N9 NPZ stays byte-identical; the derived native solution and playback count have a separate schema.
Existing replay and PreviewPolicyRegistry stay independent. The new `/current-vla/preview-preflight` POST performs
offline robot math only; GET polling never dispatches it. GUI still needs a separate explicit preview action.
See [simulator2 contract, bounded results and rollback](simulator2-integration.md).
