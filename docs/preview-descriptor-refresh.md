# Preview descriptor refresh

The final-prediction proof added for the Guided VLA/GPT33 admission contract is
mandatory in `simulator2_gate.OWNED_CODE` and the STP gate that extends it. An older
running backend could cache that list before the addition and emit a descriptor
missing `backend/services/final_prediction_proof.py`. The fresh Isaac child then
correctly rejects it before importing/creating `SimulationApp`.

`backend.refresh_preview_ux.refresh` remains the single explicit migration.
Besides its existing exact audited renderer releases, it accepts only the current
fingerprint map minus that one named file. Every existing hash must match; other
missing, extra, changed or unknown code entries fail. The unchanged normal gate
verifies source/native files, exact H5/OBJ, current job/sample/artifact and approved
mask lineage before any write. Source point counts remain 9 for Guided VLA and
33 for GPT. There is no inference, native recomputation or automatic fallback.

Refresh writes a new UUID descriptor with `ux_renderer_refresh.previous_descriptor`
and updates the mutable readiness pointer. The previous descriptor, source package,
NPZ, native solution and assets remain byte-identical. Current paths/coordinates,
orientation policy and physical execution flags are preserved.

After restarting the backend, stop any owned preview, then open **Preview descriptor
관리 → Preview descriptor 갱신** in the Simulator panel. Continue with Path Preview
and Robot Preview. This calls `POST /api/simulator/current-vla/preview-descriptor-refresh`
with exactly `{ "job_id": "<current UUID>" }`. No browser paths or code hashes are
accepted. Both cached kinds are checked before either is refreshed. No cache, unknown
release, wrong identity, changed evidence or active owned preview returns 409 with
`PREVIEW_DESCRIPTOR_REFRESH_REJECTED`. Polling and launch do not migrate automatically.

The existing explicit CLI is also available:

```powershell
.\.venv\Scripts\python.exe -B -m backend.refresh_preview_ux --artifact-id <UUID> --backend dataset_stp --kind both
```

The runner's stdlib-only `preview_startup.run_preview` rechecks the ordinary queue
gate before importing the renderer. Admission/startup exceptions write a request-
and session-bound result and `startup.native.log` even before READY. The fixed
stdout event is also preserved by the parent in `native.log`. Diagnostics contain
exception class, stage, allowlisted message/code, exit code and repo-relative
traceback frames without source lines, locals, raw exception text, keys or payloads.
The runtime reads this result even if the process already exited before READY.
HTTP status exposes only safe reason/stage/message, never the traceback.

Known missing fingerprint: `OWNED_CODE_FINGERPRINT_MISSING`; other integrity
failures: `PREVIEW_ADMISSION_FAILED`; renderer import/app startup failures:
`PREVIEW_STARTUP_FAILED`. Failed processes are cleaned up without retry.

Rollback metadata only by restoring the prior cached descriptor claim saved in
`ux_renderer_refresh.previous_descriptor` or the refresh audit. This does **not**
bypass the current gate: a descriptor missing the required fingerprint stays
rejected. Coordinated code rollback needs its matching audited descriptor. Never
edit the immutable source or disable the gate to make an old descriptor pass.

## Verified smoke (2026-10-03)

The existing `B_PR_03_0001` Guided artifact
`6384aabb-d342-43f1-a444-cef7e7339abc` was refreshed for current job
`15508a2a-e972-435f-a4e2-982bade80863`. New Path/Robot descriptor UUIDs are
`c543100a-69e9-4004-8b5e-cfa3f3dcbed1` and
`a3f24ea8-548e-4f45-9215-769489bf6284`. All 29 protected files retained their hashes,
including `.env`, old descriptors, immutable packages, source NPZ, H5/OBJ and mask.

A fresh owned temporary backend on port 18002 exercised explicit refresh
(idempotent), real Path Preview and real Robot Preview. Both completed with captures;
source count stayed 9, robot playback completed all 21 native derived points,
and both USD scenes contained the red prediction BasisCurves. The actual web MJPEG
endpoint returned a bound 1280×720 JPEG (HTTP 200); browser wiring was additionally
verified with fake Playwright E2E. Stop returned STOPPED/no PID, released ownership,
and rejected the expired stream with 409. The temporary backend was shut down.
No model was called and physics/physical robot execution remained disabled.

Evidence is in `.cache/simulator/descriptor-refresh-audits/4cc645ff-8501-4a4c-a9fe-93c3371d2c6f/`
(`report.json`, `live.json`, `robot-live.jpg`). Owned Isaac session:
`64cb313d-a6a1-4aaf-a232-d5882898ae7f`; Path request:
`b4ec6618-c911-46e1-89e6-2caf0fbc195b`; Robot request:
`0f17c717-9a33-4a3c-8925-ed7bfc334ad5`.

GPT33 migration and runtime completion passed with fake source/native fixtures;
no new GPT artifact or GPT live preview was generated. The user's existing port-8000
backend reported both previews ready after migration but had not loaded the new
refresh route; restart that backend before using the new UI button.
