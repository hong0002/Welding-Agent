# Simulator final URDF compatibility — 2026-10-06

**SIMULATOR_FINAL_URDF_COMPAT_PARTIAL**

The deprecated Kit URDF command failure is fixed. The one requested standalone
launch imported RB10 using Isaac 6.1's `URDFImporter`/`URDFImporterConfig`,
initialized its native articulation and verified the actual starting tool pose.
It then failed inside the unchanged native viewport capture function, before
playback. Standalone is not PASS, so no final adapter, selector, `.env` activation
or web integration smoke was performed. Existing `dataset_stp` remains active.

## Callsite audit

The external authoritative repository is flat `../simulator_final`.
Both legacy command names appeared in these six native scripts:

| Script | Original create / parse lines | This change |
|---|---|---|
| run_rb10_trajectory_with_ATU01035.py | 425 / 441 | Active native URDF block replaced |
| run_rb10_trajectory_3x.py | 209 / 228 | Historical entrypoint unchanged |
| run_rb10_T_PP_03_virtual_welding.py | 975 / 996 | Historical entrypoint unchanged |
| run_first_sample_alignment_check.py | 348 / 362 | Historical entrypoint unchanged |
| run_rb5_h5_weld_test.py | 96 / 106 | Historical entrypoint unchanged |
| run_validation_prediction_sim.py | 2999 / 3017 | Historical entrypoint unchanged |

The searched Welding-Agent, simulator_stp and simulator2 Python sources contained
no existing URDFImporter migration to reuse. Other historical scripts have not
been migrated or tested and may still fail on Isaac 6.1.

## Exact mapping

Installed importer: `isaacsim.asset.importer.urdf` 3.11.10, Isaac Sim 6.1.0.
The backend-owned `backend/urdf_import_compat.py` is copied unchanged into the
native root as `urdf_import_compat.py`. The main renderer calls that helper only
in place of its original URDF command block. Existing exported native USD
`rb10_trajectory_with_ATU01035.usda` supplies actual drive evidence; no arbitrary
new stiffness/damping value or generic SDK default was selected.

| Native setting | Isaac 6.1 handling |
|---|---|
| merge_fixed_joints=False | Same config field; TCP joint retained |
| convex_decomp=False | collision_type='Convex Hull'; existing source collisions retained |
| import_inertia_tensor=True | Converter retains source mass/inertia; density override=None |
| fix_base=True | Same config field; world-to-link0 fixed joint retained |
| distance_scale=1.0 | Converter uses meters; no extra scale op; other scales unsupported |
| make_default_prim=False | Reference into receiving stage without SetDefaultPrim |
| get_articulation_root=True | Locate converted ArticulationRootAPI; return its exact path |
| native drive type | acceleration, read from native USD for all six joints |
| native stiffness | USD 625; config 625×180/pi Nm/rad → USD 625 Nm/degree |
| native damping | USD/config 0 for all six joints |
| native maxForce | USD 10, restored on receiving stage's drives |
| native articulation settings | PhysX, self collision=false, solver position=32 / velocity=1, from native USD |
| destination | Native robot name `/rb10_1300e_u`, identity transform |
| asset output | Explicit owned directory; no source URDF/mesh/tool overwrite |

`run_asset_transformer=False` avoids optional variant/package restructuring.
`run_multi_physics_conversion=False` keeps native PhysX rather than generating
additional engine policy. Converter link hierarchy is nested in `Geometry`;
the existing native TCP search and Articulation initialization work with it.
No manual robot/scene coordinate adjustment was added.

Offline pxr inspection of the resulting asset confirmed: expected six joints,
one TCP, world fixed joint, meter scale=1, base origin=(0,0,0), 14 meshes, exact
drive type/stiffness/damping, and zero mass difference versus native evidence.
Joint limit differences are 0.0000152587890625 degrees from float conversion.
Actual articulation initialization succeeded in the single live launch.

## Standalone evidence

Attempt: `e191137d-e2f7-463f-972d-687451a0deb5`.
Evidence: `.cache/simulator-final-audit/<attempt>/`:
`manifest.json`, `native.log`, `result.json`, `diagnosis.json`,
`urdf_evidence.json`, native source snapshot and generated importer output.
Earlier failed evidence remains untouched.

Input: B_PR_03_0004, existing Guided artifact
`7bdec2fd-a3dc-478e-b623-ca8ae448f44d`, 9 source / 18 native playback points.
Source NPZ SHA256:
`80d07b71d0c01e18e9cf9a40910c4fad0c11c3bc74493e8a7a6f81425660ca1d`.
`predicted_source_xyz_m` exactly equals that NPZ's `predicted_path_m`.
The prepared solution is exactly equal to the earlier preparation under Isaac
Python for every saved array. H5/OBJ, registration, source_to_scene, table,
tool/TCP, IK/FK, interpolation, prediction/GT handling, camera and timing code
were unchanged. This smoke uses native `prepare()` and renderer `main()`;
no Welding-Agent Demo/sample_scene geometry was substituted.

Native preparation tip error: 0.004435 mm; flange gap: 0 mm.
After actual articulation initialization, USD tool-start verification:
mount gap=0 mm, tip error=0.000706 mm, mount-axis error=0.000002 degrees.
Logs confirm exact 412-vertex workpiece and ATU01035 attachment were authored.
Native table/pedestal/camera code executed unchanged; visible screen verification
is incomplete because capture failed.

New failure:
`capture_frame("start")` → native `capture_viewport_to_file()` task exception →
20-second capture deadline → `RuntimeError: Viewport capture failed: .../start.png`.
The preceding task exception text was undecodable in the native stdout stream.
The exact underlying encoding/image-writer cause is not established. The
non-ASCII Windows destination is a plausible lead, not a confirmed diagnosis.

Process exit=0, timeout=false. This is explicitly **not success**: no captures,
no saved final scene, no measured-weld output and no `[PLAYBACK] finished`.
The original renderer closes SimulationApp after traceback; exit status alone
does not prove completion. Owned process tree and lease were cleaned up.

The native red representation is measured tool sweep driven by prediction IK;
green is GT/reference only. Native prediction target lineage is verified offline,
but red sweep/playback lineage has not been produced in this failed execution.
GT was not substituted as robot target. Orientation remains
`fixed_initial_fixture_pose` / simulator policy; VLA orientation=false and
physical_robot_executable=false.

## Conditional work remains

The requested post-PASS investigation of the 180-degree prepare-runtime
discrepancy was not started; no extra rotation was added.
`SimulatorFinalClient` and `dataset_final` selector were not added because the
user explicitly requires standalone PASS first and integration PASS before
activation. Web Robot Preview for simulator_final was not run. Root `.env`,
legacy/dataset_v2/dataset_stp runtime code and frontend source remain unchanged.

Next minimal step is to repair or isolate the native viewport file-capture
failure, with no placement, camera, trajectory or physics policy changes, then
authorize another standalone launch. Existing Welding-Agent buffer capture code
is a relevant implementation reference; it was not silently substituted here.

## Verification and rollback

Focused fake/offline pytest: 6 passed. Backend compileall: passed. Frontend
build: passed (normal existing chunk-size warning). Full pytest was not run.
Actual Isaac standalone=1, integration=0, model calls=0. pxr-only post-inspection
created zero SimulationApp instances.

Authorized external modifications are limited to
`run_rb10_trajectory_with_ATU01035.py`'s URDF block and the new compatibility
helper. Original renderer backup and hashes:
`.cache/simulator-final-audit/urdf-compat-source-backup/`.
Rollback restores that renderer backup and removes the new external helper;
no `.env` rollback is needed because dataset_stp was never switched. This
restores the legacy importer call, which remains incompatible with Isaac 6.1.

A=YES; B=YES; C=NO; D=UNVERIFIED; E=UNVERIFIED; F=YES;
G=NOT_IMPLEMENTED; H=YES.
