# vlm_final_gpt2 native integration audit

**Current implementation:** [prediction-only boundary and live outcome](gpt2-prediction-only.md) supersedes the historical runtime blockers below. The native inference/export interface has now been minimally changed with explicit user authorization; shared retrieval and simulator_final remain unchanged.

Audit date: 2026-10-06. Source of truth: `../vlm_final_gpt2`. External predictor, old predictor and `simulator_final` were read-only throughout this work.

**Follow-up correction:** the original few-shot module has since been restored and actual import now passes. RICL query GT/baseline arrays are evaluation-only numeric inputs; they are not required by the model or native TRAIN retrieval. The native batch sample discovery/export still couples their existence/loading to Final output. Current-job input-only snapshot passes without RICL; production Final remains blocked by that unmodified native boundary. See [the current source-classified audit](gpt2-ricl-boundary.md). The missing-module findings below are retained as historical evidence of the earlier filesystem state.

**GPT2_ADAPTER_OFFLINE_PASS / NATIVE_RUNTIME_DEPENDENCIES_MISSING.** The thin adapter, native cached export replay, normalization, source selection and fake STRICT handoff pass. The actual native import/sample preflight does not pass on this PC, so no live inference, SSH retrieval or Isaac launch was attempted. The root `.env` was not changed; its current production selector remains `gpt`. This is not a live GPT2 integration PASS.

## Actual Windows blockers

- The user-confirmed `D:/Research_and_Paper/2026경남AISW경진대회/code/vlm_project2` directory **exists**, including `retrieval_client.py`, `cot.py` and previous CoT sessions. However, `vlm_final_gpt2/predict.py` imports `vlm_project2.fewshot_examples.prepare_examples`, and **`fewshot_examples.py` is absent**. Its existing `retrieve_actions()` implementation does not provide that function. After the owned Windows `fcntl` compatibility path is injected, an actual read-only import in py3_12 raises `ModuleNotFoundError: No module named 'vlm_project2.fewshot_examples'`. Evidence: `.cache/gpt2-integration-audit/confirmed-runtime.json`.
- The configured `../RICL/welding_validation_ricl_maskmix_available` baseline export is absent. The train configuration's `../RICL/welding_train_ricl_all` is also not available. The new predictor directory contains seven source/config/documentation files, with no saved native sample or outputs.
- A full dataset H5/OBJ or an old Welding-Agent result does not replace this native baseline contract. No package stub, fake baseline, `none` retrieval or old import bridge is installed in the production launcher.
- Restoring the original **missing few-shot module and its original dependencies**, plus the real native baseline export, is the minimum next operator action. If a complete package exists elsewhere, configure its parent with `WELD_GPT2_SHARED_ROOT`; configure the real baseline parent with `WELD_GPT2_BASELINE_ROOT`. Existing CoT-session `plan.json`/`retrieval.json` is not the baseline export required by the full native pipeline. Native retrieval still requires the configured SSH service and local TRAIN example assets; these were not network-probed.

## Native contract: 25 audit fields

| Field | Observed native contract |
|---|---|
| Entrypoint | `predict.py:main()`; adapter calls the original file with `runpy`, not a copied predictor |
| Execution | Fixed `C:/Users/hong_/anaconda3/envs/py3_12/python.exe`; `predict.py --config <owned resolved config> --sample-id <current sample>` |
| Config | `config.yaml`; alternative native `config_train_selected8.yaml`; relative paths resolve against the selected config's directory |
| Model | `gpt-6-luna` |
| Reasoning | `medium`, preserved from the native config |
| Arguments | Native CLI supports sample IDs, limit, modes, endpoint/ablation/resume options and `--cot-session`. The production adapter uses only config and one sample ID; no endpoint, ablation, refresh, retry or CoT session flags |
| Images | `raw_rgb/{B,F,L,R,S1,S2,S3,S4,T}_Color.png`, in that native canonical order; query JPEG resizing uses native `image_max_side=1024` |
| Masks | Native full mode reads `source_label.json` `annotation_image` / `full_welding` polylines and draws available GT seam masks with width 24. Web binary masks are not a full-mode input. `--cot-session` accepts another project contract but changes the stage pipeline, so is not used |
| Instruction | `metadata.json.instruction`; the adapter supplies the current job/explicit user instruction in an owned input snapshot |
| References | Original `prepare_examples`; resident service through SSH alias `IDEALABv2_key`, top-k 3, candidate pool 20, RRF 60, at most three views/example; original image/text/action/mask weights remain unchanged |
| Known start | Native `metadata.start_xyz`, finite XYZ in source mm. The adapter verifies equality with the exact bound H5 `trajectory[0,:3]`; it does not replace the native start |
| Rough stage | First original Responses parse request, approximately nine relative XYZ points |
| Corners stage | Second original request, using the previous response/proposal, with 2..output-count control points |
| Finalization | Original `interpolate_corners`; corner-preserving linear interpolation with original interval allocation and connection labels, followed by native `export` |
| Output files | Native `rough.json`, `corners.json`, `rough_cot.md`, `corners_cot.md`, masks, input/retrieval/signature artifacts, four CSVs, `trajectory.npz`, `metadata.json`, `status.json`; root build/summary artifacts. Native does **not** write `response.json` |
| Frame | Stage points: `source_robot_start_relative_mm`. Final: `source_robot_frame_unaligned_with_isaac` |
| Units | Source XYZ mm; native `predicted_path_m` is source XYZ multiplied by 0.001 exactly once |
| Point count | Default 9-to-33; native 4-to-9 is also supported. Adapter preserves the configured native count instead of forcing 33 |
| Orientation | No predicted orientation. Simulator orientation remains `simulator_final_policy`, `vla_orientation=false` |
| GT scope | Full mode has native GT **image seam masks**, supplied start and other TRAIN teaching examples as inputs. Query GT endpoint/interior trajectory is not a model input. Full query GT/baseline trajectories are read after prediction for evaluation; native GT resampling is retained when counts differ |
| NPZ | Ten keys below; native numeric path arrays are float64, corner indices integer and connection labels strings |
| Validation | Native structured `Proposal`, finite/control-count checks and native interpolation; adapter additionally requires complete status, correct sample/split/frame/units/start/metrics, preserved corners and source hashes. Exit 0 alone is insufficient because native can store failed per-sample status |
| Dependencies | Python 3.12.3 checked; NumPy 1.26.4, Pillow 10.4.0, PyYAML 6.0.1, Pydantic 2.10.6, OpenAI 2.15.0, tqdm 4.67.1 installed. Required `vlm_project2.fewshot_examples` is missing. Native imports `fcntl`; the owned audited Windows flock subset supplies that compatibility only |
| Working directory | The actual `vlm_final_gpt2` root; shell=False, owned process-tree supervision, UTF-8 and external bytecode writes disabled |
| Environment / key | Native `make_client` first uses `OPENAI_API_KEY`, otherwise native `api_keys_path`. The owned launcher sets the key only from Welding-Agent root `.env`; no key is written into config, manifests, logs or UI. Native SDK tracing disabled |

Native NPZ keys:

```text
predicted_path_m                 (N,3) float64, meters
ground_truth_path_m              (N,3) float64, meters
predicted_path_xyz               (N,3) float64, absolute source mm
ground_truth_path_xyz            (N,3) float64, source mm
start_xyz                       (3,)  float64, source mm
predicted_delta_xyz              (N-1,3) float64, mm
ground_truth_delta_xyz           (N-1,3) float64, mm
corner_indices                  integer vector
connections                     string vector of length N-1
original_ground_truth_path_m     original GT (M,3), float64 meters
```

Native retrieval settings retain remote root `/NHNHOME/WORKSPACE/26moe002_B/IDEA/JuyoungKim/VLA_TEST/server/vlm_embedding_server`, remote Python `/home/bk-gnu/miniconda3/envs/welding-rag/bin/python`, and weights target image .30 / full image .15 / task text .25 / action text .20 / mask shape .10. Availability of those remote assets remains unverified.

## Old failure and comparison

`OLD_FAILURE_CAUSE`: the actual old attempt `e283bc7b-33a0-488b-b36b-ec3f06ed7ec6` for B_PR_03_0001 / job `7e3a790b-59f4-440a-99f5-dbd8837b552a` saved Rough/Corners and failed with exit 1 / TypeError. An offline replay of its saved corners reproduced **`TypeError: Object of type ndarray is not JSON serializable`**. The old Welding-Agent worker puts native `interpolate_corners`' ndarray `modes` into its generated response dict before native JSON serialization. It is an adapter serialization failure, not evidence of invalid known start or a failed GPT proposal. No old production code was patched to hide it.

`GPT2_DIFFERENCE`: GPT2's original CLI owns the full exporter, writes ndarray connections directly into NPZ, supports native configurable counts and preserves original GT alongside native evaluation resampling. Its default model and core prompt/stage concept resemble the old project; selecting GPT2 alone is not proof that the unavailable retrieval dependencies work. The new adapter reads exported arrays and converts metadata to JSON lists after native export. It never reproduces that old response-writing path.

`WHY_GPT2_IS_PREFERRED`: predictor/export ownership stays in the verified native project. Welding-Agent handles admission, owned paths, lineage, normalization and UI only. Runtime verification is still required before making it production.

## Thin adapter and artifacts

`model_clients/gpt2_trajectory.py` snapshots the real matching native baseline label/NPZ, current nine RGBs and current instruction into a new UUID attempt. It changes filesystem roots for owned inputs/outputs and current bound dataset; it retains model, reasoning, prompts, retrieval, masks and native finalization. The owned resolved config sets SDK `max_retries=0` to satisfy the explicitly requested no-automatic-retry policy; the original config has 2 and remains unchanged. One full native invocation consists of **two model stages**, not one API request. There is no wrapper retry or fallback.

```text
.cache/native-models/gpt2-trajectory/<UUID>/
  inputs/<original native sample directory>/
    metadata.json, source_label.json, trajectory.npz, raw_rgb/
  native_config.yaml, launch.json, request_manifest.json, source_job.json
  submission.json, diagnostics.jsonl, native.log, process_exit.json
  native/
    build.json, summary.json, ...
    <original native sample directory>/
      rough.json, corners.json, trajectory.npz, metadata.json, status.json, ...
  owned/
    normalized.json, validation.json
  response.json, metadata.json, display.json, completion.json
  trajectory.npz                    # byte-copy of native NPZ, never reserialized
```

The root response/metadata are owned compatibility metadata, not native outputs. `owned/normalized.json` records native NPZ hash, actual count/frame/units, finite result, job/scene/instruction bindings and `xyz_modified=false`. `mask_binding=null` and `web_masks_used_as_input=false` are intentional: current web mask/approval is retained in job lineage and invalidation checks but is not falsely claimed as model conditioning. Native masks remain native artifacts. References come from native retrieval (`reference_in_request=true`, `references_supplied_by_adapter=false`); Trajectory3 is not supplied.

Partial Rough/Corners remains a separate relative display result. It is never relabelled Final. Native invalid/partial status never creates a promoted VLA result. Gaps/unknown edges remain split display runs; STRICT playback refuses disconnected or unknown connection modes rather than joining weld regions.

Completed native/owned hashes, exact H5/OBJ, original shared/source code, conditioning and native numeric arrays are rechecked on current reuse and STRICT admission. No NaN repair, alternate H5 row, start offset duplication, axis swap, source interpolation or source resampling occurs in normalization. Approval or instruction changes continue to invalidate downstream results.

## Selection and simulator handoff

Current-job/current-sample renderable results select GPT2 Final first, then GPT2 intermediate, current legacy GPT, then Guided. Previous/foreign artifacts never auto-select. Existing artifacts retain their original source. Agent uses the existing GPT tool family, selects the backend-only predictor and reuses an already verified current GPT2 Final without another native invocation.

Absolute GPT2 Final takes the existing `SimulatorFinalClient` STRICT path; relative/raw takes labelled DEMO. The original NPZ bytes reach the immutable package unchanged. SimulatorFinalClient and original simulator_final own source-to-scene, derived densification, orientation, IK/FK and playback. Focused fake handoff verifies 33 native source points / 65 simulator-derived playback points and `vla_orientation=false`; these are fixture results, not a live scene PASS. `simulator_final` was not modified and no GT replaces prediction robot targets.

## Verification and integrity

- Focused GPT2 tests: 18 PASS, using original native cached CLI/export with **explicit synthetic proposals and a fail-closed test-only import harness**. That harness is absent from production. This is native writer/interpolation/parser evidence, not a real native import or retrieval PASS.
- Related focused suite: **81 PASS** in 16.98 seconds, including those 18 GPT2 tests, source binding, legacy retrieval adapters, visibility, Robot Preview and SimulatorFinalClient. Frontend build and compileall pass. Fake Playwright: **2 GPT2 + 4 Robot-binding tests PASS**. They check GPT2 Final precedence, 33-point STRICT selection, relative DEMO selection, stale exclusion and exact artifact/stage submission. `frontend/test-results/gpt2-final-strict-offline.png` is a fake UI screenshot, not live prediction evidence.
- A wider legacy `test_gpt_trajectory.py` check has 18 failures. The identical failures reproduced after restoring the prior Workflow method and Agent tools **in memory** from Git HEAD, with no filesystem replacement. They concern stale F-only promotion, strict-known-start and idempotence expectations versus the existing F/R/S4 / visualization-first behavior. They are retained as baseline failures, not reported as a fully passing legacy suite.
- Actual external source inventory before/after: GPT2 7 files, old GPT 7 files, simulator_final 65 files unchanged. Manifests: `.cache/gpt2-integration-audit/source-before.json` and `source-after.json`.
- OpenAI/model calls 0; SSH retrieval 0; Guided VLA 0; Isaac 0. There is no live GPT2 attempt or actual Final NPZ for this integration run.

Safe machine-readable results are in `.cache/gpt2-integration-audit/offline-report.json`. Config/status checks never import the model or invoke retrieval.

## Changed integration files

Only Welding-Agent files changed in this task; unrelated pre-existing working-tree changes were preserved.

- New native boundary: `backend/model_clients/gpt2_trajectory.py`, `gpt2_trajectory_entry.py`, `backend/services/gpt2_prediction_proof.py`.
- Provider/contracts/state: `backend/model_clients/final_trajectory.py`, `trajectory_contracts.py`, `backend/schemas.py`, `backend/orchestrator/workflow.py`, `state_machine.py`, `backend/agent/tools.py`, `service.py`, `backend/main.py`.
- Source preservation and existing simulator handoff: `backend/services/current_vla_preview.py`, `simulator_prediction_package.py`, `simulator2_client.py`, `simulator2_gate.py`, `robot_demo.py`, `geometry_preview.py`, `visibility_artifacts.py`, `output_catalog.py`, `backend/current_vla_isaac_preview.py`.
- Frontend source/count/native-mask labels and selection: `frontend/src/types.ts`, `api.ts`, `App.tsx`, `SimulatorPanel.tsx`, `simulatorSelection.ts`, `components/OutputBrowser.tsx`, `FinalPredictionView.tsx`, `PathPanel.tsx`, `AgentDecisionCard.tsx`.
- Verification/config/docs: `tests/test_gpt2_trajectory.py`, `frontend/e2e/gpt2-final.spec.ts`, `.env.example`, `README.md`, `docs/architecture.md`, this report. Real root `.env`, external predictor source/config and external simulator source did not change.

## Operator configuration and rollback

After restoring original native dependencies and passing real import/sample preflight, use backend-owned UTF-8 config candidates:

```dotenv
WELD_FINAL_TRAJECTORY_BACKEND=gpt2
WELD_GPT2_TRAJECTORY_ROOT=D:/Research_and_Paper/2026경남AISW경진대회/code/vlm_final_gpt2
WELD_GPT2_TRAJECTORY_CONFIG=D:/Research_and_Paper/2026경남AISW경진대회/code/vlm_final_gpt2/config.yaml
# WELD_GPT2_SHARED_ROOT=<parent of original vlm_project2>
# WELD_GPT2_BASELINE_ROOT=<real matching native baseline export>
```

Keep the root `.env` key backend-only. The root `.env` has **not** been rewritten. Restart Backend after selecting a provider. Native full mode still needs its real matching sample export and configured original retrieval service; setting the selector does not fix missing dependencies.

Rollback: restore `WELD_FINAL_TRAJECTORY_BACKEND=gpt` and restart Backend. Existing `WELD_GPT_TRAJECTORY_*`, old artifacts and `dataset_stp` / `dataset_final` remain available. No artifact is retroactively renamed. Browser/Agent cannot provide Python, native roots, config, scripts or filesystem paths.

Next gated validation: real native import/config/sample resolution first; only after all pass, at most one authorized full GPT2 pipeline invocation, inspect native final bytes and current normalized selection, then at most one existing SimulatorFinalClient STRICT smoke. Do not generate fake inputs or auto-retry to pass these gates.

Welding-Agent → vlm_final_gpt2 native predictor → native final trajectory → Welding-Agent normalization → simulator_final STRICT
