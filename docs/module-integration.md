# 9-view AI module integration

Target: Web → 9-view Scene → Native Segment → Human Approval → NativeRough3D → Guided
VLA → VLAPredictedTrajectory → VLA_READY. This milestone is independent from Simulator.
No model/API/SSH/Isaac/physics calls were made during implementation or verification.

## Contracts and operation

1. **Scene schema.** Schema v2 retains `scene.id`, primary F dimensions/image URL and `job.mask`
   for existing callers. `sample_id`, resolved `split`, `primary_view="F"`, and `views` add nine
   image IDs/URLs/dimensions/original SHA-256s and optional per-view `Mask` metadata.
   Paths are backend-owned; browser data contains only IDs, image URLs and summaries.
2. **9-view loading.** `POST /api/scenes/sample` accepts only `{sample_id}`. Canonical order is
   `B, F, L, R, S1, S2, S3, S4, T`; names are `<sample_id>_<view>_Color.png`.
   Exact Training/Validation category/thickness/sample lookup verifies all nine label records,
   dimensions and split uniqueness. Missing/ambiguous samples fail; no full scan or similarity search.
   `WELD_DATASET_ROOT` is backend-only. Blank uses the audited owned guided-vla-inputs dataset root.
3. **One image resolution.** Upload with the known suffix requires exact original file SHA-256.
   A matching R/S4/etc upload loads the same nine-view sample and selects F. A mismatched known
   name fails 409; arbitrary names retain the existing single-image upload flow.
4. **Frontend.** Large Konva Canvas stays in place. Nine ordered thumbnails select the active
   image and show IMAGE/MASK/APPROVED/ACTIVE. Separate drafts keep brush, eraser and undo state
   across switches. F guidance is rendered on F only. Existing desktop/mobile layouts still work.
5. **Human approval.** Only actual Segment views have masks. Native masks start unapproved.
   F is the primary planning input; view confirmation includes current mask ID and view ID.
   Brush/Eraser exports source-resolution 0/255 PNG with `manual_edited` lineage.
   Any committed mask/instruction change invalidates Rough3D and VLA. Unsaved drafts block UI planning.
6. **Native Segment.** One `segment_views` launch uses the original F/R/S4 native defaults;
   the browser cannot choose argv/Python/cwd/config. Fixed py3_12, original `mask.py`, shell=False,
   native retrieval and artifacts stay unchanged. No all-nine inference or synthetic masks.
7. **NativeRough3D.** Path mode explicitly selects `native_3d` (`vlm_trajectory2`) or
   `baseline_2d` (`vlm_trajectory`). Dataset scenes default to native_3d. The immutable approved-mask
   session is generated under owned records using the existing validated native contract, leaving
   original Segment output intact. Native plan/refiner/retrieval/2D guidance/3D reference and
   `cot_ko.md` / `vla_prompt.md` remain native files. Canvas points are read directly from guidance JSON.
   Native reference 3D image can be expanded in Path; it stays marked unregistered/non-executable.
   New painted lines unsupported by the existing polyline clipping adapter fail before inference.
   Current Guided mode requires one independent F weld region; use the 2D baseline for multiple regions.
8. **Guided VLA.** `POST /api/weld/{job_id}/guided-vla` takes exactly `{}`. Server/token/path
   fields fail validation. Backend resolves split, verifies the current F approval and hashes,
   builds transfer Markdown from 2D JSON, and uses the existing `cot` + `F_mask.png` multipart
   contract. R/S4 are review-only even when individually approved. The retrieved 3D reference is
   preserved for provenance and excluded from transmission. Explicit `/health` check precedes a
   single submission; GET `/api/models/status` never probes the server. No automatic retry.
   `POST /api/models/guided-vla/check` with `{}` is an optional operator health check.
9. **Agent.** `run_guided_vla()` has no public arguments. It requires a refreshed workspace,
   current explicit Guided VLA execution intent, F approval and Rough3D. A per-turn attempt guard,
   tool lock, job admission and manual mutation guards remain. Planning alone, explanations,
   negative requests and existing sample replay intent cannot invoke Guided VLA.
   Agent output contains counts, frame, ADE/FDE and artifact IDs, never arrays/paths/token/raw COT.
10. **VLA_READY.** Spatial prediction has sample/split/model/count/XYZ/frame/ADE/FDE and false
    physical execution flags. Response/NPZ/metadata/completion/model provenance and proof hashes
    remain local. Public job has `vla_prediction` summary; image `final_trajectory` and preview
    validation remain empty. Missing model names stay null. A health model name, if supplied,
    is separately recorded with its provenance. Upstream edits invalidate the summary.
11. **Simulator separation.** VLA_READY does not start Simulator. Current B_PR gate remains
    B_PR_TOOL_CLEARANCE_FAIL, registry blocked, simulator_ready=false. Simulator tab shows VLA
    Prediction Ready / Simulator Fixture Pending and disables current VLA playback. The existing
    configured sample replay buttons retain their independent process/readiness behavior.
12. **Verification.** Pytest fixtures inject native outputs and HTTP transport. Playwright tests
    use a dedicated fake factory. Cases cover nine views, switching, F-only approval, mask edits,
    hash tampering, strict request body, request claims, Rough3D parsing, VLA parsing/state, Agent
    intent and no retry, baseline preservation, and blocked Simulator. Actual B_PR successful
    artifacts were separately replayed through the real normalizers and approved-mask adapter.
13. **Web use.** Restart backend/frontend after updating code. Enter `B_PR_03_0001` and click
    **9 views 불러오기** (or upload an original known view). Click **AI 마스크 검출 · F/R/S4**.
    Review F, optionally use Brush/Eraser, click **마스크 확정 · F**. Enter direction/selection
    in Assistant or **수동 지시 / 디버그 → 지시 분석**. Path → select **NativeRough3D** →
    **용접 경로 생성** → review 2D guidance → **Guided VLA 실행**. A ready result shows
    VLA_READY, 9 points, frame, ADE/FDE and artifact ID. The last button makes one real prediction
    only when explicitly clicked with backend credentials and the configured tunnel/server ready.
14. **Remaining Simulator milestone.** Fixture/tool clearance, source-to-scene convention and
    robot/tool pose/orientation remain deferred. No prediction fitting, GT substitution, standoff
    search, asset changes, registry enabling, Simulator queue or Isaac run was performed.
15. **Milestone verdict.** MODULE_INTEGRATION_COMPLETE for the proven primary-F contract.
    Verification is offline artifact replay; this does not claim a fresh paid inference or a
    currently reachable live VLA server. Actual Simulator execution remains blocked independently.

## Private artifacts and readiness

`storage/native_context/<job>.scene.json` stores dataset paths and original/normalized hashes.
`<roughArtifact>.rough3d.json` stores current-job/source-mask linkage and native file hashes.
`<vlaArtifact>.vla.json` stores the immutable Guided attempt link and response/package proof hashes.
None of these paths, source arrays or Markdown reasoning are passed to Agent chat.

Every Guided attempt has a new UUID with immutable source-job conditioning snapshot, request
manifest, F binary, generated guidance Markdown and byte-copied native 2D/reference provenance.
`submission.json` exclusively claims it; real HTTP has `live_called=true`, injected replay false.
Native cot/vla_prompt Markdown is preserved and is not used as request point input.

The existing operator CLI prepare/check/run remains available. Set the backend-only
`WELD_GUIDED_VLA_SERVER_URL` to the actual SSH tunnel endpoint (this deployment uses
127.0.0.1:18000) and `WELD_GUIDED_VLA_API_TOKEN` in root .env. Nothing is transmitted on startup.

## Reproducible offline verification

Verified on 2026-09-30: 319 pytest cases, 25 complete Playwright cases, production frontend
build and backend compileall passed. After the final provenance/UI clarification, the affected
80 backend cases and seven browser cases also passed. Actual B_PR browser replay passed once
with native reference image loading verified. No live model/network/Simulator calls.
Backend replay evidence: `.cache/module-integration-e2e/f525de57-eabd-47b4-bd3c-8686805d748b/report.json`.
Browser evidence: `frontend/test-results/module-integration-bpr-guidance.png` and
`frontend/test-results/module-integration-bpr-replay.png`.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall -q backend
cd frontend
npm.cmd run build
# Use installed Chrome if the local Playwright Chromium is absent; no browser download needed.
$env:WELD_TEST_BROWSER='C:\Program Files\Google\Chrome\Application\chrome.exe'
npm.cmd run test:e2e
```

Separate explicit real-artifact replay, still with zero process/model/HTTP/Simulator calls:

```powershell
# from project root
.\.venv\Scripts\python.exe -B -m tests.module_replay
cd frontend
$env:WELD_TEST_BROWSER='C:\Program Files\Google\Chrome\Application\chrome.exe'
$env:WELD_TEST_REAL_ARTIFACT_REPLAY='1'
npm.cmd run test:e2e -- e2e/module-integration.spec.ts -g '9 views'
Remove-Item Env:WELD_TEST_REAL_ARTIFACT_REPLAY
```

The replay uses existing successful Segment artifact `47300c47-24f5-4714-a480-02b732b5365b`,
trajectory2 session `20260930_154703_B_PR_03_0001` and Guided attempt
`866654a5-8cc7-4edc-82a8-0c276818aad8`, reads the actual nine source images, and creates a fresh
owned output directory. The replay parser accepts the historical native instruction using its
recorded direction; this is an explicit fixture, not a new model interpretation.
Original prediction/GT arrays are equality-checked and ADE/FDE remain
97.15410614013672 / 155.03475952148438 mm. Browser screenshot is written to
`frontend/test-results/module-integration-bpr-replay.png`.

Automatic approval review rejected expanding remote transmission to several approved views
because explicit multi-view payload/destination approval was not established. This implementation
uses the accepted existing F-only transport. R/S4 transmission expansion remains a separate action.
