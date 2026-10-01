# Guided VLA adapter — offline preparation and explicit HTTP smoke

`GuidedVLAClient` implements `POST /v1/predict-guided` with exactly `sample_id`, `split`,
`cot`, and repeated `masks` multipart fields. It does not call Segment, Rough, OpenAI,
SSH, or Simulator. Browser/Agent cannot change server/token/files/split. The explicit
Workflow Guided VLA action and `run_guided_vla()` semantic tool now reuse this exact F-only
transport; their current-job proof is described in [module-integration.md](module-integration.md).
The NativeRoughClient (also exported as NativeRough2DClient) and Dummy baseline remain available.

`NativeRough3DClient` is separate and uses a `rough3d` NativeRuntime with the fixed
py3_12 Python and sibling vlm_trajectory2, shell=False, original cot.py/config/retrieval,
and the existing owned-process supervisor. Use `configured_rough3d_client()` explicitly;
it uses the separate Workflow Rough3D Protocol rather than the image-pixel Rough/VLA protocols. V3 readback
checks plan/refiner/retrieval/2D/3D artifacts and actual selected reference points. Its
result contains `ReferenceTrajectory3D` and query image guidance. It never labels the
reference as `VLAPredictedTrajectory`.

## Backend-owned inputs

Root `.env` configures WELD_GUIDED_VLA_SERVER_URL, WELD_GUIDED_VLA_API_TOKEN (or
EX3_API_TOKEN), WELD_GUIDED_VLA_TIMEOUT, and WELD_GUIDED_VLA_INPUTS. Credentials
never enter manifests, logs, output summaries or frontend settings. Inputs/config/output
must belong to Welding-Agent; native artifacts and the dataset are read-only.

The operator-owned input JSON has exactly these keys (absolute paths):

```json
{
  "dataset_root": "D:/.../3.개방데이터",
  "binding": "D:/.../Welding-Agent/.cache/native-integration/configs/binding.json",
  "storage_root": "D:/.../Welding-Agent/<selected-storage>",
  "rough_session": "D:/.../vlm_trajectory2/outputs/cot_sessions/<session>"
}
```

The latest explicitly dated approved native/manual_edited mask for the exact bound RGB
is selected within that storage. Legacy implicit approvals do not qualify. The F-only
adapter validates full-size L-mode PNG 0/255, current scene/mask correspondence, source
mask ID, approval timestamp and file/pixel hashes. Native R/S4 files are never copied.
Missing views stay absent. The single-segment API contract rejects multiple mask regions
or guidance segments instead of flattening them.

Split is derived from the bound original RGB's Training/Validation hierarchy and its
exact matching NIA label path, sample identity, filename and dimensions. A duplicate
counterpart in the other split is rejected. No dataset scan or default-val assumption.
This maps Training to train and Validation to val; the server must confirm the same
sample/split identity during the later smoke.

## Serialization and ownership

Native query_image_guidance_2d.json is the numeric source of truth. Native plan.json is
used only for identity and structured direction/grounding decisions. Markdown files are
never parsed for coordinates or modified. Pixel/normalized consistency is checked with
the native image dimensions. Normalized values are serialized with round-trip float
precision and unchanged point order; `forward`/`reverse` is carried separately, preventing
an adapter-side double reversal. Server direction semantics still need live confirmation.
At least 80% of guidance points must be near the current mask's own region within 2px.
This is a preview consistency check, not robot safety validation.

Each preparation creates `.cache/native-models/guided-vla/<UUID>/` with exclusive writes:

```text
request_manifest.json
guidance.md
masks/F_mask.png
query_image_guidance_2d.json
reference_trajectory_3d.json  # byte-copy provenance, never uploaded
```

Manifest records source identities, approvals, file/pixel hashes and split proof.
Source and package hashes plus latest approval are checked again before HTTP. A
submission.json exclusive claim allows one request per attempt, even after failure.
No retry wrapper or output overwrite. After valid response: response.json,
trajectory.npz, metadata.json, completion.json. Completion is written last; partial
files never indicate success.

`ReferenceTrajectory3D` preserves retrieved_teaching_start_relative/mm and
registered_to_query=false. It is excluded from the request. `VLAPredictedTrajectory`
holds response XYZ/frame/mm separately, always is_robot_executable=false. Neither is
cast into the current image_pixel FinalTrajectory or automatically sent to Simulator.
Each validated VLA response has a backend-generated artifact UUID, also recorded in
metadata.json. Server/task metadata cannot replace that identifier.

## Response validation

Request/response sample ID and split must match. Prediction and GT must each be finite
numeric (9,3), frame must be a nonempty string, metrics finite/nonnegative. A supplied
guidance_mode must be nonempty and not none. Missing guidance_mode is allowed per the
available contract and does not prove guidance use. task_metadata is nested separately;
it cannot overwrite episode/frame/unit fields. Extra unsupported response keys are not
exported. Credentials/hidden-reasoning fields are excluded from persisted metadata.
Numeric token-count telemetry in cot_delivery is preserved; it is distinct from secret
API/access tokens. cot_delivery is recorded in both response.json and metadata.json.
When delivery metadata is present, original/delivered token counts must match, truncation
must be explicitly false, and chunk token counts must sum to the delivered count.
The observed server fields are original_cot_tokens/delivered_cot_tokens and
chunk_token_counts. A nine-slot array can contain one nonempty F slot; that does not
mean nine nonempty COT chunks. Missing delivery metadata alone remains permitted.
NPZ writes float32 predicted_path_m/ground_truth_path_m using scale 0.001, independently.
GT is never substituted for prediction.

The frame validator deliberately does not claim simulator compatibility from a nonempty
name. Actual response frame/source origin/axes, known GT start oracle input, guidance
delivery, and H5 correspondence require later validation. No orientation is invented.
The B_PR simulator fixture remains unsupported. No model invocation or simulator action
is exposed by preparation/check or automatic tests.

## Operator CLI

From repository root:

```powershell
.\.venv\Scripts\python.exe -m backend.guided_vla prepare
.\.venv\Scripts\python.exe -m backend.guided_vla check --attempt-id <UUID>
```

Only after explicitly authorizing a live smoke and configuring the backend token/tunnel:

```powershell
.\.venv\Scripts\python.exe -m backend.guided_vla run --live --attempt-id <UUID>
```

That command calls only Guided VLA once. It does not open an SSH tunnel or run native
models/Simulator. No token is passed on the command line. prepare/check summaries contain
resolved sample/split/count/views/endpoint and token-configured boolean, never point arrays.
The current local preparation is B_PR_03_0001, train, F, 9 normalized points. Missing token
blocks run, not offline preparation. The URL is configuration only; prepare does not probe it.

Tests use tiny owned fixtures, fake native output/processes and injected HTTP transports.
Run `python -m pytest tests/test_guided_vla.py` without model/network credentials.
