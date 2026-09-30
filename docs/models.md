# Segment / Rough integration

Real VLA is deferred at the user's request. Final path and geometry validation remain a **Dummy
VLA 2D preview**. Existing simulator sample controls are unchanged. Nothing here sends a current
web path to EX3, Isaac or a physical robot.

See [source inspection and actual contracts](model-contracts.md). Neither provided VLM is a local
GPU model: both call OpenAI. This integration imports their existing prediction functions and
prompts in independent, bounded Python workers. No source code, model weights or training data
were copied. `GET /api/models/status` does not run inference or make network calls.

## Setup on Windows

Keep the running backend's `.venv` separate. From the Welding-Agent project root, the operator
can create independent environments using Python 3.10+ (these commands install libraries, not weights):

On the inspected PC, both `.venv-model-segment` and `.venv-model-rough` have now been created
with Python 3.12. Their dependency checks and offline external-function probes passed. Local `.env`
has their interpreter paths and explicit `none` reference modes, while BACKEND selections remain
Dummy. To try real mode here, change the two BACKEND values below and restart the backend; no
reinstallation is needed. These local environments and `.env` are ignored by Git.

```powershell
py -3.12 -m venv .venv-model-segment
.\.venv-model-segment\Scripts\python.exe -m pip install -r ..\vlm_segment\requirements-mask.txt -c backend/model_clients/runtime-constraints.txt
py -3.12 -m venv .venv-model-rough
.\.venv-model-rough\Scripts\python.exe -m pip install -r ..\vlm_trajectory\requirements.txt -c backend/model_clients/runtime-constraints.txt
```

Set root `.env`, keeping the existing `OPENAI_API_KEY` backend-only. Use forward slashes and
the **actual absolute executable paths** for this installation:

```dotenv
WELD_SEGMENT_BACKEND=real
WELD_ROUGH_BACKEND=real
WELD_SEGMENT_PYTHON=D:/Research_and_Paper/2026경남AISW경진대회/code/Welding-Agent/.venv-model-segment/Scripts/python.exe
WELD_ROUGH_PYTHON=D:/Research_and_Paper/2026경남AISW경진대회/code/Welding-Agent/.venv-model-rough/Scripts/python.exe
WELD_SEGMENT_REFERENCE_MODE=none
WELD_ROUGH_REFERENCE_MODE=none
WELD_SEGMENT_CAMERA=web
WELD_ROUGH_CAMERA=web
WELD_SEGMENT_TIMEOUT=120
WELD_ROUGH_TIMEOUT=180
WELD_AGENT_RUN_TIMEOUT=420
```

**Reference choice is explicit.** `none` invokes the existing callable with the uploaded image
and no few-shot examples; it does not run the original RAG retrieval. For fixed approved examples,
use `fixed` and `WELD_SEGMENT_REFERENCES` / `WELD_ROUGH_REFERENCES` pointing to a JSON manifest.
The original retrieval starts from dataset sample IDs and Linux SSH/data paths. It is not wired
to arbitrary web uploads, and the adapter never scans the dataset or guesses a sample ID.
Prediction accuracy in image-only or fixed-reference mode has not been evaluated.

The external YAML supplies the model names, reasoning effort, mask band width, and rough point
budget. The currently inspected model name is `gpt-6-sol`; access has **not** been tested. Restart
the backend after changing settings. Real mode never silently falls back to dummy after a failure.
Leaving both BACKEND values as `dummy` preserves the existing development flow.

Status distinguishes `NOT_CONFIGURED`, `UNVERIFIED` (local files/settings present, no verified
inference), `RUNNING`, `READY` (a previous worker result passed), and `FAILED`. Ready is not a live
remote health probe. Missing Python packages are detected on explicit invocation, not on every poll.

## Reference manifests (backend configuration only)

Paths resolve relative to the manifest. Use one to three actual reference samples; never supply
the query's GT as a reference. Images must be prepared by the model project's established flow.
An uploaded view defaults to the honest label `web`, with no camera calibration assumption.
`camera` must match the configured label; using F/R/etc is an operator assertion about the view.

Segmentation:

```json
{
  "schema_version": 1, "stage": "segment", "camera": "web",
  "examples": [{"sample_id": "REFERENCE_ID", "original": "original.png", "overlay": "correct_green_mask.jpg"}]
}
```

Rough: each `item` is the complete reference object from the original `retrieval.json` results,
including `sample_id`, `metadata`, `texts` (task/action, ko/en), `mask.available_views`, and
`rough_action`. `sheet` and `action_plot` refer to the original generated reference visuals.

```json
{
  "schema_version": 1, "stage": "rough", "camera": "web",
  "examples": [{"item": {}, "sheet": "mask_views.jpg", "action_plot": "rough_action.jpg"}]
}
```

The empty `item` above illustrates placement only and is deliberately not a runnable example;
fill it with the original retrieved item. Browser requests cannot supply paths, programs,
Python interpreters, references, checkpoints or credentials.

## Manual and AI masks

`/api/masks/automatic` accepts `job_id`, optional `min_component_area`, and `instruction`.
Configured real segmentation calls external `predict_camera` once and external `rasterize`.
No threshold is invented: the external model returns center polylines, rasterized into 0/255 PNG.
The existing 8-connectivity/noise filter assigns regions; the original binary image is retained.

AI masks appear in the same canvas layer as brush/eraser edits. Binary PNG background becomes
transparent in the display layer; opacity only affects display, never exported values. Editing
sets `manual_edited`, and the previous mask UUID is retained. The current binary mask is always
the source for planning. A stale edit base is rejected. Clear/undo include both the base AI image
and subsequent brush strokes. No stale original VLM polylines override manual edits.

The rough adapter explicitly converts each active component to an open, unbranched skeleton
chain (`binary-skeleton-chain-v1`). It rejects branching, closed loops, degenerate shapes,
components with bounding boxes over 2 million pixels, over 64 active regions, or excessive work.
This is a **lossy 2D conversion**, not 3D seam recovery. Broad blobs may not represent an unambiguous
weld centerline. Repaint a narrow open seam if rejected. The original external `simplify_segments`,
instruction refiner and semantic planner then run. No original prompt/weight is altered.

Original pixel and normalized outputs are cross-checked. Only original pixel points enter the
existing image_pixel preview schema; normalization is never applied twice. Model segment IDs
map explicitly to backend region IDs in the confirmed order. Changed direction/order, omitted
regions, duplicate decisions, enabled welding during travel, or connecting segments are rejected.
Existing own-component proximity validation still applies; it does not certify interpolated edges.

## Agent and artifacts

`auto_segment_weld_region()` requires explicit detection intent in the current message and a
fresh workspace check. User-indicated manual masks are not replaced. “내가 다시 표시할게” waits.
`create_current_weld_plan()` owns rough → Dummy VLA → preview validation order. The old
`create_weld_preview_plan()` remains an alias. Existing simulator tools and SQLite sessions remain.
SSE stage starts/completions come from actual backend transitions; errors close the failed stage.
GPT receives IDs/counts/frame/units/status, never model point arrays, images or hidden reasoning.

Scene, mask, rough, final and validation have optional version-1 artifact envelopes, compatible
with existing schema-v2 snapshots. They retain source scene/mask/rough IDs, instruction, region IDs,
model/prompt version, UTC timestamp, measured worker latency and source/config fingerprint where
available. Hosted checkpoint identity is unknown (`null`). Actual worker files and model-native
JSON stay in `.cache/models/<UUID>`; a run's output is correlated by the artifact provenance ID.
No absolute model/checkpoint path appears in the public artifact schema. Existing immutable mask
snapshots preserve the earlier AI provenance through `edited_from_mask_id`.

## Explicit, one-image smoke

Configuration check only (safe offline; does not invoke either model):

```powershell
.\.venv\Scripts\python.exe -m backend.model_smoke segment
.\.venv\Scripts\python.exe -m backend.model_smoke rough
```

Only the operator's explicit `--live` triggers actual paid OpenAI requests:

```powershell
.\.venv\Scripts\python.exe -m backend.model_smoke segment --live --image C:/samples/query.png --instruction "용접할 영역을 찾아줘"
.\.venv\Scripts\python.exe -m backend.model_smoke rough --live --image C:/samples/query.png --mask C:/samples/confirmed-mask.png --instruction "왼쪽에서 오른쪽으로 용접해"
# After the two separate smokes pass, use ONE common image:
.\.venv\Scripts\python.exe -m backend.model_smoke pipeline --live --image C:/samples/query.png --instruction "용접할 부분을 왼쪽에서 오른쪽으로 용접해"
```

For right-to-left smoke also set `--direction right_to_left`. Pipeline smoke means **segment →
rough → preview geometry checks**, with no real VLA or simulator. It is not a three-model E2E.
Each request has a fixed worker deadline and zero automatic retries. Rough uses one refiner call
and one planner call. No training, benchmark, SSH setup, model download or dataset full scan.
Reports under `.cache/models/smoke` record success/error, per-stage and total latency; remote
GPU peak memory is `null` because telemetry is unavailable. Timeout defaults are provisional.

Errors: `MODEL_NOT_CONFIGURED`, `MODEL_NOT_READY`, `MODEL_TIMEOUT`, `MODEL_OOM`,
`MODEL_INPUT_INVALID`, `MODEL_OUTPUT_INVALID`, `MODEL_PROCESS_FAILED`. Public responses contain
only fixed messages; raw SDK errors/prompts/credentials are not surfaced. OOM never causes retries.
