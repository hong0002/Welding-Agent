# GPT2 prediction-only boundary

## Current retrieval blocker (2026-10-06)

The original `IDEALABv2_key` value is not a Windows SSH Host alias: it resolves
literally to hostname `idealabv2_key`, user hong_, port 22 and absent default
keys. The historical failed attempt preserved only RuntimeError, so its exact
transport error cannot be reconstructed. Existing successful Segment/Rough
parity configs supply evidence for `IDEA-DEV-1` with the identical remote root
and Python. One simple transport probe to that alias passed.

Read-only remote checks on IDEALABv1 found the configured root/Python, native
modules, cached encoders, CUDA/FAISS GPU, nine query RGBs and TRAIN indexes/actions.
All four actual service modules import; unrelated missing timm/scipy are not
native prerequisites. Native `service.action_rpc --status` cannot connect to
its node-local abstract Unix socket. The original resident contract may start
`service.action_daemon`; one genuine `prepare_examples` precheck attempted this
and failed before returning references or calling GPT. Native daemon traceback
ends at its instance flock with BlockingIOError, errno 11. A later read-only
nonblocking flock confirmed the instance lock remains busy. The lock lives on
Lustre, while this node has no matching resident socket or visible lock owner.
Another node holding the lock is a possibility, not an established owner.

No retrieval cache was fabricated or borrowed. Local returned-reference asset
resolution and live Rough/Corners/Final remain NOT_RUN. No paid attempt,
production switch, backend restart or Isaac call is admitted until genuine
retrieval and local TRAIN references pass. Root .env remains unchanged.

The Welding-Agent-owned launcher now observes original function boundaries,
SSH exit/category, timeout, native RPC startup reason and parser stage in
`retrieval_diagnostics.json`. It does not replace transport, parser or scorer,
retain raw errors/payloads, change native code, or retry. Backend-only optional
`WELD_GPT2_RETRIEVAL_SSH_ALIAS` changes solely resolved `server.ssh_alias`.
Resident mode, remote root/Python and retrieval weights/ranking stay original;
there is no automatic one-shot fallback. The candidate alias is not persisted
to root .env because native runtime is still blocked.

Operator prerequisite: identify the owner/node of the shared
`service/action_resident_instance.lock`, restore/check the original daemon on
the intended node, and provide a verified Windows Host alias that reaches it.
Use the native `service.action_rpc --status --timeout 10` under the configured
root/Python to require `status=ready`. Do not delete a lock file or kill an
unverified process. No replacement daemon, remote code edit or package install
was performed. Diagnostics are in `.cache/gpt2-retrieval-audit/`; the complete
safe report is `report.json`.

Focused fake/native-parser tests cover success, DNS/auth/module errors, resident
startup failure, malformed JSON, timeout, redaction and restoring instrumentation.
Adapter tests verify the SSH-only override leaves model/reasoning/retrieval/counts
unchanged. Tests never start SSH or a model. Previous offline parity is preserved.

The native CLI now supports `--prediction-only`. It accepts current metadata,
source_label and the nine canonical RGB views without a query trajectory NPZ.
Native `prepare_examples`, TRAIN retrieval, Rough/Corners, Proposal, model,
reasoning, prompt and `interpolate_corners` are unchanged. Known start remains
metadata.start_xyz, verified against the exact current H5's first XYZ before
launch. Native export adds that start once and multiplies by 0.001 once.

`trajectory.npz` schema `gpt2-prediction-only-v1` contains six native keys:
predicted_path_xyz, predicted_path_m, start_xyz, predicted_delta_xyz,
corner_indices and connections. Metadata/status identify the schema, completion,
sample/split/frame/mm/config and evaluation_performed=false. There are no GT
arrays or ADE/FDE, no baseline reads and no evaluation CSVs. Output has its own
`__prediction-only` namespace. Default benchmark CLI keeps its original ten keys,
GT/baseline metrics, four CSVs and summary. `evaluate.py` explicitly skips
prediction-only exports instead of trying to evaluate absent GT.

The owned launcher executes native predict.py with a fixed Python, original cwd,
UTF-8, shell=False and a Windows Job Object. Its SDK retries are explicitly zero
for the authorized single attempt. Root .env is the only key source; logs contain
allowlisted stage/exception milestones. The adapter copies native NPZ bytes,
normalizes native XYZ without coordinate math and requires complete status,
source/point/unit/start/provenance hashes. Partial Rough/Corners never become
Final. Web edited masks/approval remain lineage: native Full uses dataset seam
labels, not those edited pixels. No Trajectory3 coordinates are injected.

Final responses/summaries have null GT metrics. UI shows “Prediction only · GT
평가 미실행”, while current GPT2 Final keeps selection priority and validated
renderable state. No fabricated metric is displayed. Existing Guided/old GPT
contracts retain mandatory metrics and their original counts.

## Unmodified simulator_final compatibility

The native simulator still requires ground_truth_path_m for sample/frame
diagnostics. Its interface is unchanged. Only dataset_final creates a separate,
owned simulator diagnostic companion: native_prediction.npz is a byte copy of
the six-key native output; trajectory.npz copies every native prediction array
exactly and adds real GT from the bound current H5, index-resampled for diagnostic
length matching. No GT enters GPT requests or native prediction export. No GT
is substituted for robot XYZ. Both files, exact H5/OBJ, current approval/job and
native simulator files are sealed and revalidated before STRICT admission.
Orientation remains simulator_final_policy, vla_orientation=false; no DEMO
transform or adapter alignment is applied. A changed companion prediction or
diagnostic GT fails admission. Physical execution remains disabled.

## Verification and current live outcome

Focused offline native cached replay compares all six prediction arrays with
default evaluation mode and the pre-change exporter: maximum XYZ difference 0.
Tests prove finite native count, one start addition, one unit conversion, genuine
no-NPZ query inputs, no evaluation reads, default metrics/CSV compatibility,
immutable normalization, partial rejection, source priority and fake STRICT.
The parity baseline exporter and protocol fingerprints in tests/fixtures are
offline fixtures only, never production predictors or fabricated query inputs.

Windows verification runs with `python -X utf8 -m pytest` to emulate the fixed
native launcher's UTF-8 mode; compileall and frontend build also pass.
Fake Playwright covers Final priority/STRICT, relative intermediate selection,
null metrics and existing Robot button binding. No tests invoke paid models,
SSH or Isaac.

Real B_PR_03_0001 input/import passed in py3_12 without a query NPZ. One authorized
attempt was made, UUID `7fe7f6f0-4350-4fb3-a8fe-a21d0ef8b0bf`, job
`7e3a790b-59f4-440a-99f5-dbd8837b552a`, split train. It exited 1 after about
17.7 seconds during native TRAIN retrieval: SSH calls 1, GPT stage calls 0,
retrieval.json absent, Rough/Corners/Final absent, native RuntimeError. The
discarded raw error/SSH payload is not available; the exact transport/service
cause is not established. No retry, production switch, backend restart, Guided
VLA, Segment, Trajectory3 or Isaac call occurred. Logs and the partial attempt
are retained. Offline adapter is ready; live production readiness is pending.

Evidence: `.cache/gpt2-prediction-only-audit/{preflight,live-result,source-before,source-after}.json`
and the attempt's diagnostics.jsonl, diagnostics.native.log, invocation_counts.json.
Only native predict.py, evaluate.py and README.md changed. Shared retrieval,
model configs, interpolation and simulator_final are unchanged.

After a separately authorized successful live Final, select
WELD_FINAL_TRAJECTORY_BACKEND=gpt2 and restart the backend; optional one STRICT
smoke comes afterward. Current root .env stays on its prior selector. Rollback
is WELD_FINAL_TRAJECTORY_BACKEND=gpt plus backend restart; dataset_stp remains
available. Native backups and exact source hashes are in the owned audit folder;
restore only the three interface files if rolling back native CLI support.

## Windows LOCAL retrieval boundary (2026-10-06)

`WELD_GPT2_RETRIEVAL_MODE=local` is the environment default. Its backend-only
root is `WELD_GPT2_LOCAL_RETRIEVAL_ROOT`, defaulting to the sibling
`vlm_embedding_server`. The owned source loader imports native Python source
and calls `service.action_runtime.search` directly. No SSH, resident RPC, lock
or index generation is used. Index, query encoding, weights, candidate pool,
top-k, TRAIN filtering and reference materialization remain native.

Windows faiss-cpu 1.8.0.post1 lacks GPU transfer APIs. Its CPU branch loads the
same IndexFlatIP bytes and uses native `.search()`; Korean paths use native
deserialize_index over read-only bytes when fopen cannot open them. A GPU API
installation retains original resource/index functions. The image indexes are
768D/1199 vectors, task/action indexes 768D/1156, mask index 72D/1156; all use
inner product. No external service source, index or manifest was modified.

The user explicitly authorized only facebook/dinov2-base and
intfloat/multilingual-e5-base downloads. Cache is `.cache/model-encoders/hub`.
Recorded revisions are `f9e44c814b77203eaa57a6bdbbd535f21ede1415` and
`d128750597153bb5987e10b1c3493a34e5a4502a`. Native encoder calls use CUDA;
owned children force offline cache loading. See
`.cache/gpt2-local-final-audit/encoders.json` for exact snapshot paths.

One authorized B_PR_03_0001 LOCAL smoke passed: native retrieval 12.813s,
reference preparation total 13.656s, FAISS searches 0.110s, whole smoke 16.046s.
Top-3 TRAIN references were B_PR_M_0001, B_PR_M_0011, B_PR_M_0002; query
self-exclusion and reference images/actions passed. CPU/GPU top-k parity is
NOT_AVAILABLE. Original scores/component scores, hashes and timings are in
`.cache/gpt2-local-final-audit/authorized-smoke-result.json`.

A live attempt may reuse this genuine retrieval.json only through the native
frozen-cache interface after exact fingerprint, request and hash checks.
This does not become a global cache for other jobs. No automated test invokes
OpenAI, retrieval models or Isaac. Focused adapter/trajectory tests passed
(23 tests). Production selector changes only after a successful real Final.

### Authorized live Final PASS

After explicit authorization of native query/reference data transmission to
OpenAI, attempt `3e866fbb-54a7-4a59-9baf-bf07456d9f3c` completed in 92.813s,
exit 0. Rough and Corners each called once and succeeded. The successful LOCAL
smoke artifact was reused without another search; retrieval/SSH/Isaac calls 0.
No automatic retry occurred. Native rough.json, corners.json, metadata.json,
status.json and prediction-only trajectory.npz are preserved under
`.cache/native-models/gpt2-trajectory/<attempt>/native/output__prediction-only/B_PR_03_0001`.

Final is 33/33 finite XYZ in source_robot_frame_unaligned_with_isaac. Native
source XYZ are mm; meter XYZ exactly equal source XYZ times .001. Recomputing
the original interpolate_corners and adding known start once matches every
source XYZ exactly. The adapter NPZ is a byte copy. Query GT endpoint/interior,
baseline NPZ and unnecessary local paths were absent from model input.
Only WELD_FINAL_TRAJECTORY_BACKEND changed in root .env, from gpt to gpt2;
backend restart is required. Rollback remains selector gpt plus restart.
See `.cache/gpt2-local-final-audit/{live-result,final-verification}.json` and
the immutable attempt proofs. Simulator live validation was not performed.

### STRICT gate import boundary

The current artifact `4a3e566a-8bfe-4510-a449-6ac208515dbf` belongs to native
attempt `7e00447c-9df0-4c0d-bc51-f8f3af9ae45a` and current job
`f6b980f0-6bf7-4939-9168-58a9f463750a`. Its conditioning and immutable hashes
match. The generic PREVIEW_ADMISSION_FAILED message came from ModuleNotFoundError
for dotenv: companion verification unnecessarily imported backend package/settings
code into the pre-GUI gate. It now reuses the same SHA-256 helper from the prediction
proof module, without reading .env or requiring backend settings in the gate.

An explicit dataset_final descriptor refresh accepts only the exact audited
previous companion fingerprint, rechecks all ordinary source/package/approval/job
gates and creates a new UUID descriptor. Unknown code or changed evidence fails
closed. Native prediction, source snapshots, simulator package and native IK/FK
solution remain unchanged. The refreshed readiness claim for the above artifact
passes the full gate offline even with backend settings/dotenv imports blocked.
No prediction, SSH, preparation or Isaac launch is part of this migration.
