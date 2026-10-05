> Current policy (2026-10-05): [Visualization first](visualization-first.md) supersedes the historical known-start block and retrieval no-fallback statements below. Invalid starts permit relative visualization; retrieval can downgrade segment2_adapter → local → none for visualization only. Historical failure evidence remains unchanged.

# Final GPT trajectory: owned retrieval integration

**Verdict: PARTIAL — offline adapter ready; the single live attempt failed before retrieval because the selected query H5 has a NaN initial Y coordinate.**

The original `vlm_project2.fewshot_examples` is still absent. It was not restored. An explicitly authorized owned replacement is injected through a process-local import bridge; external projects/config/assets remain read-only. Earlier missing-module-only verdicts are superseded by this implementation.

## Segment2 comparison

| Contract | Actual Segment2 | GPT requirement / owned adapter |
|---|---|---|
| Inputs | retrieval payload, dataset root, one camera, output directory, line width | native seven arguments, with backend-bound current 9 RGB / approved F binary / instruction / Trajectory3 polylines |
| Output | `mask.prepare_examples` returns sample ID, RGB path, green mask-overlay path tuples | Responses input text/images and retrieval provenance |
| Retrieval query | `retrieval_client.retrieve_sample`: RGB upload → server YOLO query manifest → DINOv2 full/target similarity | actual native image selector reused; owned category/text/F-mask/2D-geometry reranking |
| Sample IDs | returned native `results[].sample_id` with scores | top-k IDs preserved; self and duplicate IDs rejected |
| TRAIN filtering | server `service.retrieve` defaults to TRAIN index and reports `index_split` | require TRAIN/server_yolo/query identity/self-exclusion proof; independently resolve each local label/image split before H5 reading |
| Images | mask target overlay for one camera | all nine TRAIN RGB with native green annotation overlays; query RGB use only approved human F mask |
| Instruction | Segment2 has no trajectory instruction loader | native TRAIN category/H5-derived teaching description, explicitly labeled as derived rather than original user text |
| Teaching target | Segment2 segmentation mask | actual TRAIN H5 XYZ via read-only `prepare_actions.build_record`, native discontinuity/simplification, source-start-relative teaching answer |
| Provenance | native retrieval JSON and IDs | query/ref hashes, TRAIN split, native/final ranks, scores, label/H5/nine-image/teaching-action hashes, aggregate dataset digest |

**Reuse verdict: PARTIALLY_REUSABLE.** Same-named Segment2 mask example builder is not a drop-in trajectory builder. Its image selector, RGB loading, rasterization and overlay utilities can be reused. Trajectory3 is used only for pure TRAIN teaching preparation utilities; neither its planner nor Segment2 inference runs here.

## Explicit retrieval modes

`WELD_GPT_RETRIEVAL_MODE` accepts exactly:

- `segment2_adapter`: original Segment2 `server_yolo` RGB retrieval, candidate pool 20 / final top-k 3 from native final config. Require remote TRAIN proof and local exact TRAIN identity. Rerank weights: image .55, category .15, instruction n-gram .15, F mask/Trajectory3 geometry .15. This is an owned replacement algorithm, not claimed original-retrieval parity. Remote pretrained loading uses `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`.
- `local`: explicitly selected bounded same-family TRAIN search, at most 128 label records and 64 image candidates. Small RGB histograms, category/text/geometry similarity; no embedding download, Validation scan or full recursive dataset scan. It is a lightweight heuristic with no accuracy-parity claim.
- `none`: no selection or teaching reads. Native no-retrieval prompt mode; UI/result provenance says **Retrieval: None** and warns that accuracy is unverified.

No mode automatically falls back to another. Configuration is backend-only. Default Segment2 config: `.cache/native-integration/configs/segment2.windows.yaml`; an operator can set `WELD_GPT_RETRIEVAL_CONFIG` explicitly.

The native seven-argument callable is produced by `owned_preparer(options)` and injected as `vlm_project2.fewshot_examples.prepare_examples` only inside the worker process. No sibling Python file/package is created. Imports suppress external bytecode writes. Reference artifacts and private full native retrieval live inside the owned UUID attempt.

## Leakage and native prediction

Query inputs contain nine RGB, current approved F binary, instruction, workpiece categories and the explicitly permitted H5 `trajectory[0,:3]` known start. Current mask and Trajectory3 2D geometry participate in retrieval ranking. Query labels provide categories/dimensions only; query GT annotation is not used. Query H5 endpoint/interior GT and Trajectory3 reference XYZ never become model inputs. Evaluation GT is read only after both GPT stages complete.

Native `call_stage`, `check_proposal`, developer prompt `gpt-luna-path-corners-v2`, rough/corners stages and `interpolate_corners` remain unchanged. Model: `gpt-6-luna`; reasoning: `medium`; native timeout 180 seconds / output token limit 5000. External config remains unchanged. The owned invocation overrides SDK retries to **0** as requested; no retry wrapper exists.

Output contract remains `rough.json`, `corners.json`, `response.json`, `trajectory.npz`, plus owned metadata/proof/display. Raw stage output is saved before structural acceptance. Accepted output requires 33 finite source XYZ in mm, `source_robot_frame_unaligned_with_isaac`; NPZ is meter conversion only, without alignment/GT correction. Separate finite display runs survive invalid output, but Simulator admission remains blocked.

Source/job/mask/approval/scene/T3/native config/source hashes, retrieval implementation hashes and nested reference artifacts are verified and retained. Current-reference source hashes are also rechecked on result reuse. Agent calls only `run_final_trajectory_prediction`; it does not create XYZ. In GPT mode Guided VLA is never dispatched or used as a fallback.

## Runtime and one-attempt result, 2026-10-05

Root `.env` was conditionally updated after changed-contract offline checks passed:

```dotenv
WELD_FINAL_TRAJECTORY_BACKEND=gpt
WELD_GPT_RETRIEVAL_MODE=segment2_adapter
```

Other settings/secrets were preserved. A private ignored backup and hash-only change receipt are under `.cache/gpt-retrieval-audit`. Backend port 8000 was restarted to apply the selector. No Isaac process was running at restart.

| Evidence | Result |
|---|---|
| Current job | `d5fce6ef-1312-49cf-9c3b-905424bfd174` |
| Query | `C_PP_03_0001`, train, latest existing validated Trajectory3 result |
| Approved F mask | `a416166b-291a-4add-85e0-812aa17d022b`, approval `2026-10-05T06:40:35.559603+00:00`; unchanged |
| Attempt | `f9c9e27a-b066-4ea8-a42c-9e69a8261fc5` |
| API | exactly one POST to existing generic final route; HTTP 503 / `GPT_TRAJECTORY_PROCESS_FAILED` |
| Native exit | 1; safe worker exception `ValueError`; no retrieval/stage event or result file |
| Read-only diagnosis | exact query H5 trajectory shape `(150,6)`, float32; first XYZ finite flags `[true,false,true]`, NaN flags `[false,true,false]` |
| Root cause | native known-start validation failed before retrieval / SDK client construction |
| Real calls | GPT/OpenAI 0, SSH retrieval 0, Segment2 0, Trajectory3 planner 0, Guided VLA 0, Simulator/Isaac 0 |
| New prediction | no rough/corners/response/NPZ; no 33-point result or new ADE/FDE |
| Job after failure | `ROUGH_PATH_READY`, original approved mask and upstream results retained |
| Automatic retry | 0; failed attempt/evidence retained, no second attempt |

The initial `submission.json` marks the launcher as claimed/live-intended; it is not proof of an OpenAI HTTP request. Stage position and the read-only preflight establish that the SDK was not reached.

A post-failure fix checks the exact first XYZ **before attempt creation or native dispatch**. Invalid/missing/empty/nonfinite H5 start returns `GPT_TRAJECTORY_KNOWN_START_INVALID` through REST and Agent safe errors. It never searches for another GT row or invents/replaces coordinates. Existing partial evidence and external H5 were not rewritten. Configuration readiness and sample-specific input readiness remain separate.

For additional offline evidence, the three TRAIN IDs in this job's **existing** Segment2 retrieval were independently resolved and passed the actual owned teaching/image builder: `C_PP_06_0001`, `C_PP_12_0001`, `C_PP_03_0002`. Each has nine image payloads and one native H5 teaching segment; H5/dataset hashes are in `existing-train-teaching-audit.json`. This is not new/live retrieval evidence.

## Simulator handoff / UX

The existing GPT33 STP/dataset_v2 handoff is preserved and tested with fake output. Immutable source NPZ is byte-copied, derived playback is separate, source count stays 33, simulator policy owns orientation and `vla_orientation=false`. Physical execution remains disabled. No new simulator source/renderer change or actual Path Preview occurred because the selected query never produced a valid final prediction.

Frontend runtime label is **GPT Final / Predictor: vlm_final_gpt**. Retrieval mode is shown for the selected runtime and separately for immutable raw results. Existing results retain their actual source/mode after a runtime change. Generic errors now include safe retrieval/configuration/known-start reasons, never paths or secrets.

## Verification

- Fixed `py3_12/python.exe`: actual native module and `call_stage/check_proposal/interpolate_corners` import pass with the owned bridge.
- Final adapter/native fake SDK/GPT33/handoff tests: **81 passed**, including the new Agent admission regression. Actual native fake SDK test performs rough/corners without network, checks native prompt/model/reasoning, 27 TRAIN+query images, and 33-point interpolation.
- Full offline suite attempt: 844 passed, 2 failed, 1 error. Two atomic writes hit Windows `WinError 5`; a semantic multi-region completion assertion failed. All failed/error categories passed a fresh targeted recheck: 15 passed. Earlier full attempt: 844 passed / 2 temporary atomic-write failures; related check 82 passed. No storage/approval assertion was weakened. A clean whole-suite result is not claimed.
- Fake Playwright final run: **10 passed**, including the known-start error UI and unchanged approval, GPT Segment2/None mode labels, raw projections, Agent routing and independent multi-region mask/Rough regressions.
- Frontend build and backend compileall/diff check passed; existing >500 kB bundle warning remains.

Automated tests use fake processes/SDK/HTTP transports and the explicit `tests.agent_e2e_app` factory. `tqdm` was added as a small dependency for native pure utility imports; no model downloads occurred.

## A–F / next action

A. **PARTIALLY_REUSABLE**: use Segment2 image selection/utilities, not its mask teaching target.
B. **Offline YES**: the owned native-compatible bridge works without the original module; live prediction has not succeeded.
C. **segment2_adapter selected**: controlled live attempt stopped before retrieval. Local/none are explicit tested alternatives, not used as live fallbacks.
D. **vlm_final_gpt-compatible GPT trajectory predictor**, never Orchestrator XYZ.
E. **NO** Guided VLA final dispatch in GPT mode.
F. **NO** actual inference success; API/SDK stage was never reached.

Remaining blocker is this query's invalid known start. A further live smoke requires a valid existing approved sample/H5 input and separate authorization for another attempt. This task does not repair external H5 or choose substitute coordinates. Rollback is an explicit operator change to `WELD_FINAL_TRAJECTORY_BACKEND=guided_vla` followed by backend restart; no automatic fallback is added.

## Changed files

- Owned predictor/retrieval/worker: `backend/model_clients/gpt_trajectory_retrieval.py` (new), `gpt_trajectory.py`, `gpt_trajectory_entry.py`, `trajectory_contracts.py`.
- API/schema/proof/errors: `backend/main.py`, `backend/schemas.py`, `backend/services/final_prediction_proof.py`, `backend/agent/tools.py`.
- Frontend: `frontend/src/types.ts`, `api.ts`, `App.tsx`, `components/PathPanel.tsx`, `components/FinalPredictionView.tsx`; retained final-intent label changes in `components/AgentDecisionCard.tsx`.
- Dependencies/config: `backend/requirements.txt`, `backend/requirements-lock.txt`, `.env.example`; private root `.env` selector/mode only.
- Tests: `tests/test_gpt_trajectory_retrieval.py` (new), `tests/test_gpt_trajectory.py`, `frontend/e2e/final-trajectory.spec.ts`; retained final/rough intent regression changes in `tests/test_semantic_workflow.py`, `frontend/e2e/agent-decision.spec.ts`.
- Retained intent migration: `backend/agent/decision.py`, `backend/agent/prompts.py`.
- Documentation: `README.md`, `docs/architecture.md`, this report.

Private non-secret receipts: `.cache/gpt-retrieval-audit/controlled-live.json`, `preflight-readonly.json`, `existing-train-teaching-audit.json`, `environment-change.json`, `pytest.log`, `pytest-final.log`. Failed native evidence remains at `.cache/native-models/gpt-trajectory/f9c9e27a-b066-4ea8-a42c-9e69a8261fc5`; no old artifacts were overwritten. Backend was restarted again after the admission fix and remains configured as GPT/segment2_adapter. Read-only verification confirms exactly one submitted GPT attempt and no final prediction for this job.
