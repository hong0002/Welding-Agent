# GPT2 query input versus RICL evaluation boundary

**Follow-up implementation:** the audit below describes the pre-change boundary. Native `--prediction-only` now removes the query evaluation NPZ dependency. See [current interface, parity and single live outcome](gpt2-prediction-only.md).

2026-10-06 follow-up. This report supersedes the earlier interpretation that the RICL baseline is a model/retrieval dependency. External `vlm_final_gpt2`, restored `vlm_project2` and `simulator_final` remain unchanged.

**RICL_REQUIREMENT_VERDICT=MIXED.** The configured root is a query export container (sample I/O plus input metadata/RGB/2D seam labels), while its trajectory NPZ contains evaluation GT and a previous baseline prediction. Those two trajectories are not input to the default full-mode GPT requests or native few-shot retrieval. However, the current unmodified native batch CLI and final exporter require that NPZ, so an input-only snapshot cannot complete native Final export. No prediction-only / no-evaluation CLI option exists.

The earlier statement “real RICL baseline is necessary for GPT prediction” was too broad. It is necessary for the **current native batch/export implementation**, not for building the two inference requests. The source functions and tests below establish that distinction.

## Source usage classification

Line numbers refer to the read-only source inspected during this audit.

| Source / function / line | Classification | Actual use |
|---|---|---|
| `config.yaml:1`, `config_train_selected8.yaml:1` | C SAMPLE_IO_ONLY | Select validation/train query export containers, respectively. Their names do not establish model dependence |
| `predict.py:52` `source_split`, `:61` `selected_split` | C SAMPLE_IO_ONLY | Read and normalize metadata split; no trajectory values |
| `predict.py:450` and `:466-473` `main` | C SAMPLE_IO_ONLY | Resolve baseline root, enumerate immediate child metadata directories and select sample ID. **Enumeration requires trajectory.npz existence** before any paid call |
| `predict.py:507-509` `main` source signature | C SAMPLE_IO_ONLY | Stat NPZ and nine RGB files for cache identity. No numeric GT load, but NPZ absence blocks this path |
| `predict.py:171-179` `input_content` | A MODEL_INPUT_REQUIRED + C | Read native label schema, finite supplied start, mm/frame, current instruction, workpiece categories. Start is an explicitly allowed input, not an inferred endpoint/interior |
| `predict.py:190-223` `input_content` | A MODEL_INPUT_REQUIRED | Read nine canonical RGBs and available 2D seam-label polylines; draw native masks and image overlays. No trajectory NPZ load in default mode |
| `predict.py:107-117` `endpoint_context`; `:184-185` | A MODEL_INPUT_REQUIRED **only in optional --end mode** | `enabled=False` returns before NPZ load. `--end` reads query GT last XYZ and puts known end/offset into context. Production adapter never selects that mode |
| `predict.py:419-436` optional `--cot-session` branch | A, optional alternate mode | Imports approved external plan/masks, may inherit endpoint condition and skips native Rough. Not used by the full two-stage adapter; no Trajectory3 XYZ is injected |
| `predict.py:244-271` `call_stage` | A MODEL_INPUT_REQUIRED | Whitelisted query context/images plus original retrieved TRAIN examples; Corners also sees the previous GPT proposal. No query GT/baseline prediction added |
| `predict.py:561-565` `main` | B RETRIEVAL_REQUIRED | Calls original `prepare_examples` with current sample ID, instruction, 2D polylines, sizes, output directory and dataset root. No RICL NPZ argument |
| `vlm_project2/fewshot_examples.py:19-24` `training_files` | B RETRIEVAL_REQUIRED | TRAIN labels and images under `data_root/2.데이터(NIA)/Training`; independent of query RICL root |
| `fewshot_examples.py:27-78` `prepare_examples` | B RETRIEVAL_REQUIRED | Search/cache payload contains ID, task text and 2D mask descriptor/polylines. Original SSH retrieval is required unless its original valid cache applies; query H5/GT path is not sent |
| `fewshot_examples.py:79-126` `prepare_examples` | B RETRIEVAL_REQUIRED | Other TRAIN sample IDs, local TRAIN RGB/GT seam labels and returned TRAIN `rough_action` teaching templates become reference input. Query sample is explicitly excluded |
| `predict.py:577-578` `main` | Native prediction finalization | Original `interpolate_corners` first generates final relative points, then calls `export`. No RICL numeric arrays are used by interpolation |
| `predict.py:278-289` `export` | D EVALUATION_ONLY | Reads query `ground_truth_path_m` and previous `predicted_path_m`; resamples evaluation paths if necessary and computes current/baseline metrics. **This load precedes prediction=start+points and any Final file write** |
| `predict.py:290-293` `export` | Native output + D | Native NPZ combines predicted XYZ/meters/deltas/corners/connections with GT, original GT and start. There is no native prediction-only output schema |
| `predict.py:294-312` `export` | E OPTIONAL_REPORTING + D | CSVs and metadata carry GT/current/baseline metrics. Reporting is conceptually optional but not optional in the current native function |
| `predict.py:332-358` `summarize` | E OPTIONAL_REPORTING | Aggregates native current and baseline metrics. It assumes the evaluation fields exist for completed exports |
| `predict.py:361-381` `resume_queue` | C SAMPLE_IO_ONLY | Checks destination metadata/NPZ completion and cached response availability; not a GT model input |
| `interpolate.py:24-48` `interpolate_corners` | Native prediction finalization | Model control points/connections/count only; no GT or baseline |
| `interpolate.py:51-69` `uniform_arc` / `metrics` | D EVALUATION_ONLY in exporter/evaluator | Metrics/GT and baseline comparison resampling. No query GT used to correct prediction |
| `evaluate.py:17-21`, `:87-150`, `:190-293` | D + E | Discover RICL/OpenVLA/GPT exports, load predicted/GT arrays, compare metrics and produce tables. Separate benchmark/evaluation program; not invoked by the adapter |

## Leakage and minimum inference inputs

For default full mode (`--end` and `--cot-session` absent): query GT endpoint/interior trajectory, full `ground_truth_path_m` and old baseline prediction **do not enter** the Responses request. Known start and dataset 2D GT seam annotations are explicit native conditioning, and are not presented as generated predictions. Retrieved TRAIN teaching examples are separate from query GT.

Minimum query snapshot:

```text
metadata.json:
  episode_id, split, instruction
  start_xyz: finite XYZ, exact source H5 trajectory[0,:3], mm
  source_units: mm
  coordinate_frame: source_robot_frame_unaligned_with_isaac
source_label.json:
  exact current sample label; native categories and 2D seam annotations
raw_rgb/{B,F,L,R,S1,S2,S3,S4,T}_Color.png
```

Sample/split are local identity fields. Model context is exactly `instruction`, `known_start_xyz_mm`, `coordinate_frame`, `camera_order`, `workpiece_metadata`, plus native image/mask content. Full H5, OBJ, old prediction, query GT endpoint/interior and unrelated local paths are not added to the model input. No query `trajectory.npz` is created.

Original native TRAIN retrieval retains its configured SSH alias/service, TRAIN index, available local TRAIN labels/images and returned reference teaching actions. A complete query RICL dataset is not required by that function. Its real SSH availability is untested in this no-network audit.

## Implemented owned snapshot and actual current-job check

Added `backend/model_clients/gpt2_query_snapshot.py` and `GPT2TrajectoryPredictor.snapshot_query`. The independent boundary stages current bound sample inputs without calling native inference or requiring RICL. It verifies stored job conditioning, sample/split/label identity, original and normalized RGB hashes, finite first H5 XYZ and copied bytes. Web edited binary masks remain job lineage; they are not converted into invented native polylines. Original native dataset seam labels are retained.

Actual current job **7e3a790b-59f4-440a-99f5-dbd8837b552a**, B_PR_03_0001 / train:

```text
.cache/native-models/gpt2-query-inputs/0c12a26e-04fb-4400-b8cc-813870b2ee11/
  inputs/B_PR_03_0001/
    metadata.json
    source_label.json
    raw_rgb/                 # nine actual current source RGBs
  snapshot.json              # QUERY_INPUTS_STAGED_ONLY, native_invocations=0
  observed-native-input/     # original input_content output; no model request
```

Original native `input_content` successfully reads this actual snapshot: nine images, native available mask views F/R/S4, finite start, and the exact whitelisted context above. No NPZ is present. Original job bytes, F approval, current/previous output and downstream artifacts are unchanged. This is **input-builder PASS**, not a Final prediction or claimed native invocation. Evidence: `.cache/gpt2-ricl-audit/current-query-check.json`.

The actual restored shared module imports successfully in the fixed py3_12 environment using the owned Windows flock compatibility path. No test package stub was used for the new real-import/input checks.

## Remaining native boundary and safe admission

Without a query NPZ, unmodified `main()` fails at line 466 before model calls. If inference functions are invoked individually, original `export()` still raises at line 278 before writing any Final output. It loads **both** genuine GT and an old baseline prediction. Catching that error leaves no native absolute Final NPZ; accepting Rough/Corners as Final would violate source ownership and the requested artifact contract.

Therefore this task does not insert a fake NPZ, zero/random GT, old prediction as GT, GT as baseline prediction, runtime replacement of the native exporter, AST rewriting, a copied coordinate calculation or a reimplemented interpolation. The existing full native compatibility path remains available for genuine native exports, but is not labelled production without RICL.

Admission/status now describes this as `GPT2_NATIVE_EVALUATION_EXPORT_REQUIRED`, with `ricl_required_by_model=false` and `baseline_dependency_scope=batch_sample_io_and_evaluation`. It no longer describes missing RICL as a model/reference dependency. `gt_metrics_optional=false` and `production_without_ricl=false` reflect the **current unmodified native CLI/export**, not a theoretical inference requirement. The root `.env` remains unchanged and selector remains `gpt`.

The minimal future native interface is an input-only sample-discovery option and prediction-only export before optional GT/comparison/report loading. It must retain original Rough/Corners, prompts, interpolation, one start addition and one mm→m conversion; optional evaluation would consume real GT separately. That interface does not exist now. Providing it requires an explicit native boundary change or a new source-of-truth release, which is outside this request's “source modified=NO” constraint. No simulator_final change is needed.

## Verification

- Actual native import: PASS; actual current-job native input builder: PASS.
- Seven new tests use the actual native/shared imports and deny live OpenAI/HTTP/subprocess transport. They verify query-only snapshot, request whitelisting, two fake stage requests without query arrays, CLI existence gate, export failure before writes, original TRAIN retrieval using fake transport, finite-start rejection and stale-input rejection. No fake query NPZ is written by these tests.
- Focused suite: **34 PASS** (`test_gpt2_ricl_boundary.py`, `test_gpt2_trajectory.py`, `test_gpt_simulator_handoff.py`). Compileall PASS; frontend build PASS. Vite's sandbox temp-write restriction required the same local build outside that restriction; source changes were not needed.
- Source/config hash inventories before/after include GPT2 7 files, restored shared project 18 files and simulator_final 65 files. All unchanged in this task. `.cache/gpt2-ricl-audit/source-before.json`, `source-after.json`.
- Model calls 0, SSH calls 0, Isaac calls 0. No new Final, production switch or simulator handoff was claimed.

```text
RICL_REQUIREMENT_VERDICT=MIXED
RICL_QUERY_GT_USED_BY_MODEL=NO (default full mode; known start and 2D seam labels are explicit inputs)
RICL_QUERY_GT_USED_ONLY_AFTER_PREDICTION=YES (numeric NPZ paths; plus non-numeric CLI existence/stat gates)
CURRENT_WELDING_AGENT_INPUTS_SUFFICIENT=YES (actual query builder PASS)
NATIVE_INPUT_SNAPSHOT_POSSIBLE=YES
FEWSHOT_REFERENCE_DEPENDENCY=original TRAIN index/service, local TRAIN RGB/labels, returned teaching examples
GT_METRICS_OPTIONAL=NO (current native CLI/export; conceptually separable)
GPT2_PRODUCTION_WITHOUT_RICL_BASELINE=NO (unmodified native Final export is coupled to evaluation)
VLM_FINAL_GPT2_SOURCE_MODIFIED=NO
MODEL_CALLS=0
SSH_CALLS=0
ISAAC_CALLS=0
```
