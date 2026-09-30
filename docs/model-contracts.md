# Model integration inspection — 2026-09-30

> Historical image-only investigation. The active integration now uses the parity-verified native CLI.
> See [models.md](models.md) for the current approval, artifact and 9-view contract.
> The web centerline adaptation below is experimental only, never the native route.

Scope update: the user deferred real VLA integration. Segment and rough adapters are in scope;
the existing Dummy VLA remains a clearly labelled image-pixel preview. No current-plan simulation.

## Evidence and source integrity

Read only: sibling `vla`, `vlm_segment`, `vlm_trajectory`. None contains `.git`, an AGENTS file,
a local checkpoint, or a supplied Python environment. No dataset scan or external source edit.
SHA256 fingerprints of sorted relative filenames plus each file's SHA256 (top-level `*.py`,
`requirements*.txt`, `config/*.yaml`; credentials and outputs excluded):

| Folder | Files | Before |
|---|---:|---|
| vla | 2 | `1789ecc683a2854898e68db32fff4969c771fcc652c1a4999b51892d334c9f92` |
| vlm_segment | 8 | `b42b0b4408f2472020ac45b8b2d496518db977ceeb31005f8aeb53922bb86d74` |
| vlm_trajectory | 11 | `9506aada2db5aebf242a6b8c66a21245f6ce448910f75547ddf92b3b87259055` |

## Segmentation: actual contract

`vlm_segment/mask.py:predict_camera` accepts an OpenAI client, model, effort, sample label,
instruction, camera label, query image path, original/annotated reference image pairs,
and optional previous prediction/feedback. It uses `responses.parse`, not a local GPU model.
`CameraMaskPrediction` contains camera_id and independent center polylines of x/y pixels.
Coordinates refer to the **original image resolution**, top-left origin, x right/y down.
`mask_data.image_data_url` converts to JPEG and downsizes images larger than 2048 pixels for
transport; the original-size coordinate contract is unchanged. No coordinates may be rescaled again.

`mask_data.rasterize` renders the polylines as a binary centerline band (configured width 24),
with rounded vertices and round endpoint disks. This is not a probability mask or a polygon interior.
Raw output is L-mode uint8 PNG, background 0, foreground 255, same width/height as RGB.
The comparison JPEG with GT/prediction colors is not the raw mask.
Read-only artifact check: session `20260929_192328_B_PR_03_0001`, iteration 1,
F/R/S4 prediction PNGs all 1920×1080, L, exactly {0,255}.

The original CLI `python mask.py --sample-id ... --instruction ... --once` performs
sample-ID-based SSH retrieval and local dataset lookup before prediction. Its Linux paths are
not a working Windows configuration. Its loader recursively scans the dataset; adapters must not call it.
The callable permits explicit reference lists, including an empty list. A web adapter must make
reference mode explicit; it must not pretend that arbitrary uploaded RGB participated in the
original remote sample-ID retrieval.

## Rough trajectory: actual contract

`vlm_trajectory/cot.py` loads an accepted mask session containing **vector polylines**,
sample images/metadata, and language. `build_query_rough_action` calls the existing deterministic
`trajectory.simplify_segments`: normally 9 points total, minimum 2 per independent polyline,
budget overflow when necessary. It emits both `points_pixel` and `points_normalized` (divide
by width/height), `source_mask_id`, `segment_id`, and `connected_to_next=false`.
The frame string is `mask_normalized:<camera>`. No orientation or robot coordinates.

`refine_instruction` and `generate_plan` use OpenAI structured outputs (`RefinedTask`,
`DetailedPlan`). They determine semantic direction/selection/operations; they do not predict new
XYZ coordinates. Reference retrieval uses sample IDs, approved masks, a shape descriptor and
refined text, followed by dataset lookups. Output `welding-cot-v2` includes the rough action,
plan decisions, operation order and response IDs. Korean/English markdown is an operation plan,
not hidden reasoning and not an EX3 API input.

Read-only artifact check: `20260929_205959_B_PR_03_0001/iteration_001/plan.json` uses
`welding-cot-v2`, primary F, one independent segment, 9 pixel and normalized points, a forward
weld decision. The exact server model and determinism are not established; OpenAI calls are stochastic.

### Explicit web adaptation

The confirmed binary mask remains authoritative for manual, AI, and edited AI masks. A versioned
binary-to-centerline adapter is required, not a claim that the external module accepts binary input.
Each 8-connected retained component is thinned independently at original resolution. Only a single
unbranched open chain is accepted per component; branched, closed or degenerate skeletons are
rejected for human correction. No component bridge, 3D projection or query GT is introduced.
This conversion is lossy and does not infer a physically correct seam from a broad painted area.
Existing module functions perform the subsequent simplification and semantic planning.
Model decisions must match the backend's explicit selected region order and direction; disagreement
is an error, not silent selection changes. Point/component geometry is checked before acceptance.

References: optional, explicitly configured fixed reference manifests, or explicit image-only mode.
Automatic retrieval for arbitrary uploads is not connected. This changes reference selection,
not the external prompts, model weights or simplifier. Artifacts record the selected mode.

## VLA: inspected, deferred

`vla/ex3_client.py` POSTs `/v1/predict` with only `{sample_id,index,split}` and X-API-Key.
It has no RGB, mask, rough, instruction, robot-state or action-history request fields.
Response `predicted_path_xyz_mm` and `ground_truth_path_xyz_mm` must be finite (9,3).
The client converts float32 mm to meters using 0.001 and saves `trajectory.npz`, prediction.json,
metadata.json. Server implementation/weights and normalization internals were not supplied.
User documentation identifies the original H5/model robot frame; exact origin, axes, tracking point,
orientation and fixture transforms are not established by the client.
The user's `/health` example reports ready, model `ex3-best-ade-epoch-17`, 9 waypoints, 3 dimensions;
this is documentation, not a live health observation.

No real VLA adapter or call is enabled in this scope. Do not send web artifacts as invented API fields,
replace current results with an existing sample, or convert these 3D points into image_pixel.
Future tunnel setup should use local port 18000 to avoid the web backend's 8000; credentials must
remain in local secret settings. No SSH/private key or token was copied into this repository.

## Environment / GPU / lifecycle

Source syntax requires Python 3.10+. Segment requirements: OpenAI, Pydantic, Pillow, PyYAML;
both include NumPy; rough also adds h5py/tqdm. Actual external Python versions are not supplied. Backend currently
uses its own Python 3.12 environment. Separate explicitly selected Python executables are used
by fixed, one-shot integration workers; no dependencies are automatically merged or installed.
Workers import existing functions read-only, disable external bytecode writes, and keep generated
files under this repository. No training, checkpoint downloads, dataset scan, SSH preparation,
or automatic external CLI main() invocation.

Implementation follow-up: independent `.venv-model-segment` and `.venv-model-rough` Python 3.12
environments were created inside Welding-Agent and their original requirements installed with
tested version constraints. Both pass `pip check` and the offline source compatibility probe.
These are new integration environments, not a claim about the original remote server environment.

Local observation: RTX 4080 SUPER, 16376 MiB total, 7419 MiB used, driver 591.86 at inspection.
These modules do not load local CUDA weights. Remote dtype, checkpoint size, peak VRAM and inference
latencies are unknown. Therefore do not start three persistent GPU services or claim they fit locally.
Sequential on-demand requests with a bounded deadline and zero automatic retries are appropriate.
Timeout defaults are provisional, not measured performance. Status only checks local configuration;
it never calls OpenAI, loads a model, probes SSH or launches inference.

## Simulator gate

Current preview remains image_pixel, 2D and `is_robot_executable=false`. EX3's meters alone do not
establish the simulator's frame, tracking_point, mounted_fixture_v2 transform, orientation or
trajectory_solution contract. No simulate_current_plan tool; existing sample playback stays separate.

## Smoke gates

Ordinary tests use fake workers/clients, never OpenAI/EX3/Isaac. Live segmentation invokes one
prediction; live rough invokes one external refiner and one planner as the existing flow requires.
User instructions prohibit automatic real OpenAI calls during development. Live smoke commands
must therefore be run explicitly by the operator. A real three-model/common-sample E2E smoke
is deferred with VLA; segment→rough→Dummy preview is never reported as a real three-model result.
