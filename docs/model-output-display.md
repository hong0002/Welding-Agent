# Model output display policy

Model output visibility is independent of acceptance. Native files stay immutable,
and raw visibility never implies approval, validated conditioning or execution.

| Shared `model_output.status` | Display | Downstream |
|---|---|---|
| OUTPUT_MISSING | No model geometry artifact | Blocked |
| OUTPUT_MALFORMED | Safe availability/reason codes only | Blocked |
| OUTPUT_RAW_DISPLAYABLE | Actual pixels/finite native points | Blocked for this raw output |
| OUTPUT_VALIDATED | Same original output, validated style | Existing approval/admission gates still required |

`WeldJob.raw_segment_output` is separate from `scene.views[*].mask` / `job.mask`.
Failed Segment contract, metadata or provenance validation preserves the previous
accepted masks, including approval timestamps. Current-run raw PNG/polygon/polyline
display evidence is preserved independently. A successful Segment result still
requires explicit human F approval. Raw editing explicitly selects a current
display snapshot UUID and uses Brush/Eraser; binary export is a human save action,
not automatic model normalization. Backend rejects changed UUID/view/scene binding
and continues full binary/dimension/component validation. Its provenance is
`manual_edited`; native approved-mask session generation remains unchanged.

`WeldJob.native_output.candidate` remains the strict parsed candidate. A hard
acceptance failure may leave it absent while `model_output.segments` still displays
the original finite native coordinates. Each native segment has separate runs.
Invalid/nonfinite points split runs and are counted, never joined across the gap.
Partial guidance without a completed plan is partial display only. Clarification
without any geometry has no fabricated path. No smoothing/interpolation/skeleton,
snapping, reversal, region reassignment or GT fitting occurs in the display reader.

Minimal basis: resolved camera/view, known dimensions and image-pixel coordinates
or decodable PNG/polygon. Missing native size may use the bound scene view with a
warning. Known foreign sample or different dimensions are diagnostic only. Explicit
nonpixel frame without a conversion basis, all nonfinite points, no geometry,
missing files and wholly malformed JSON/PNG are unavailable for geometry display.
Readers have bounded byte/pixel/point limits; safe codes describe parse/limit errors.

Display copies live at `<storage>/native_display/<job UUID>/<artifact UUID>/` with
private hash binding under `native_context`. These copies contain finite coordinates
or sanitized grayscale PNGs only. Native file lists/reasoning/payloads are not copied
into Agent events. `GET /api/weld/{job_id}` includes both reports, validation issues,
display flags/warnings and downstream flags. The only new image endpoint is
`GET /api/weld/{job_id}/model-output/segment/{view}/image`, verified against this job's
current report, immutable display hashes and fixed camera names, with `no-store`.
No arbitrary paths, prompt/Markdown endpoints or unbound history overlays exist.

The public read can show immutable historical display evidence after an acceptance
lineage mismatch, marked FAIL/RAW. `Workflow.admit_job` retains strict Agent
admission and `verify_native_output` retains strict downstream proof checks.
Guided VLA, current Simulator Path/Robot Preview and physical execution gates are
unchanged. Physical execution stays disabled; `simulator_allowed=false` for 2D
display data, including validated guidance. A new job starts without prior layers.

Canvas: solid validated path, dashed raw path, dotted partial runs; separate raw-mask
label/border and lower-opacity layer. Inspector separates output generated/count,
validation/reason, display visible/diagnostic/unavailable and downstream policy.
Use **모델 출력 보기**; for invalid raw masks use **Raw 마스크 검토·수정**, edit,
then explicitly confirm. Displaying it never sends it to Guided VLA or Simulator.

Regression suites: `test_model_display.py`, native-output preview/Agent/clarification
tests and `model-display.spec.ts`. They use fake native processes, offline transport
and isolated Playwright servers; no model, YOLO, SSH, Guided VLA or Isaac live calls.

## Changed files

- Backend display and admission: `backend/schemas.py`, `backend/main.py`,
  `backend/orchestrator/workflow.py`, `backend/model_clients/model_display.py`,
  `backend/model_clients/native.py`, `backend/model_clients/native_candidate.py`,
  `backend/model_clients/contracts.py`.
- Safe Agent reporting: `backend/agent/context.py`, `backend/agent/service.py`,
  `backend/agent/tools.py`.
- Canvas/Inspector: `frontend/src/App.tsx`, `frontend/src/MaskCanvas.tsx`,
  `frontend/src/api.ts`, `frontend/src/mask.ts`, `frontend/src/types.ts`,
  `frontend/src/styles.css`, `frontend/src/components/ModelOutputSummary.tsx`,
  `frontend/src/components/PathPanel.tsx`.
- Offline fixtures/regressions: `tests/agent_e2e_app.py`,
  `tests/native_stack_fakes.py`, `tests/test_model_display.py`,
  `tests/test_native_output_preview.py`, `frontend/e2e/model-display.spec.ts`,
  `frontend/e2e/native-output-preview.spec.ts`, `frontend/e2e/yolo-overlay.spec.ts`.
- Documentation: `README.md`, `docs/architecture.md`,
  `docs/native-output-preview.md`, `docs/model-output-display.md`.

## Verification on 2026-10-02

The complete pytest run executed 686 cases: 685 passed; one pre-existing storage
`os.replace` operation hit Windows `WinError 5` on a new temporary trajectory JSON.
That case (`test_api.py::test_separate_steps_and_right_to_left`) immediately passed
alone in a fresh temporary directory. No assertion/functional failures remained;
storage semantics were not changed to hide the host filesystem intermittency.
The new display suite covers accepted/unapproved/invalid/provenance/foreign/malformed
and polygon-only masks, raw edits/UUID binding, immutable hashes, exact/partial/NaN
paths, frame/dimension resolution, native clarification, safe Agent summaries,
legacy proof compatibility and zero downstream dispatch for rejected outputs.

Frontend TypeScript/Vite build, backend compileall and Git whitespace check passed.
The final complete fake Playwright regression run passed all 59 tests, including
raw-mask editing/approval, separate partial runs, accepted-path styles, Undo,
clarification, stale sample switching and existing native artifact replay.
Vite retains its existing large-bundle warning. Live calls for Segment2,
Trajectory3, YOLO, Guided VLA, OpenAI, SSH, Simulator and Isaac are all zero.
