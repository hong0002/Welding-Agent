# Welding-Agent development guide

## Goal and architecture
Build a runnable Human-in-the-Loop welding research MVP for the 2026 Gyeongnam AI/SW competition. The current pipeline is RGB upload → selected binary 2D mask → structured instruction → rough preview → VLA preview → preview geometry validation. React/TypeScript/Konva uses REST to call FastAPI/Pydantic. Workflow state and artifacts are stored locally.

## Multiple welding regions (schema v2)
- Mask may contain multiple disconnected welding regions.
- Each disconnected welding region must be represented as an independent weld segment.
- Different weld segments must never be connected as a continuous welding path by the orchestration layer.
- Travel motion between welding regions is a separate future robot-planning concern.
- Use `PreviewTrajectory.segments[]`, each with `segment_id`, `region_id`, `mode="weld"`, and `points`. Never flatten segments into a single rendered or transmitted polyline.
- `coordinate_space` is exactly `image_pixel`; all values remain 2D preview pixels.
- Analyze masks with 8-connectivity. Assign region IDs by the first foreground pixel in raster order before area filtering; IDs can have gaps and are stable for identical masks, not across arbitrary mask edits.
- Default minimum area is 16 pixels, configured through `WELD_MIN_COMPONENT_AREA` or a mask API request. Preserve the original binary PNG; filter only planning regions. Store the threshold with each mask.
- Resolve `start_region`, `region_order`, and `skip_regions` as integer IDs against the confirmed mask. Reject unknown IDs, duplicates, inconsistent order, and an empty active selection.
- Refine each segment independently and preserve ordered segment/region correspondence. Validate this before accepting a plan.
- Preview sanity requires at least 80% of each segment's points to fall within a 2-pixel square neighborhood of its own component after rounding. This does not validate all interpolated edges or robot safety.
- Keep endpoints and workflow order compatible. On reading v1 jobs, back up the original snapshot, retain RGB/mask, invalidate legacy polylines, and require re-parsing/replanning. Never label an old bridged result as validated v2.

## Model responsibilities
- Manual mask is 2D visual conditioning data and must not be automatically converted into 3D coordinates.
- Manual and automatic masks use the same Mask schema. Preserve original normalized scene dimensions and grayscale PNG values 0/255.
- GPT must never invent robot coordinates.
- GPT is an orchestrator, not a trajectory generator. It interprets language and selects semantic tools.
- The backend state machine remains authoritative. Agent tools reuse Workflow validation/transitions.
- The current web preview trajectory is not executable in Isaac.
- Existing simulator sample and current preview must never be conflated.
- Rough Path clients generate trajectories; VLA clients refine them using RGB, mask, rough trajectory, raw language, and structured instruction.
- Dummy trajectories are image-pixel previews, never robot commands.
- Robot execution must never be directly triggered by an LLM.
- Preview geometry validation is not robot safety validation. Web trajectory submission and hardware execution require separate future interfaces and gates.

## Development rules
- Modify only this repository. Do not modify external research projects, OpenVLA, installed models, or Isaac Sim (including D:\isaacsim).
- Keep segmentation, instruction parsing, rough path, VLA, validation, and Isaac integration behind replaceable Protocol interfaces; inject implementations into Workflow.
- Keep all state transitions in the backend. An upstream mask/instruction edit must invalidate downstream results. Reject out-of-order requests.
- Keep frontend display opacity separate from binary mask data. Export masks at full source resolution.
- Use Python 3.10+, FastAPI, Pydantic v2, pytest, React, TypeScript, Vite, and Konva. Support Windows PowerShell without Docker.
- No model downloads or physical robot execution. OpenAI calls are supported only for user-initiated Assistant requests or the explicitly invoked live smoke; never invoke them during automated development/tests. User-triggered launch of the existing simulator sample is supported through the independent SimulatorClient only.
- Never hardcode secrets. Ignore .env, local environments, generated storage, and node_modules. Provide .env.example.
- The file-based storage is for a single backend process. Do not claim multi-worker or production safety.
- Prefer focused changes with meaningful tests; document API/adapter changes in README.md and docs/architecture.md.
- Keep AgentRunner injectable; use fake Runner/offline SDK models in pytest and the explicit tests.agent_e2e_app factory in E2E. Never start real OpenAI/Isaac in tests.
- Keep API keys backend-only in root .env; disable SDK tracing and never expose raw SDK events, hidden reasoning, exception payloads or point arrays to chat.
- Preserve same-session/job run admission, manual mutation guards, max turns and tool serialization. Current workspace overrides conversation history. Mask auto-sync belongs to frontend preflight.

## Existing simulator launcher
- The sibling simulator repository is external and read-only. Modify integration code only here. Do not modify its scripts, input H5 files, assets, or exported VLA predictions.
- Web preview trajectories (`image_pixel`, `is_robot_executable=false`) are NOT sent to the simulator. The simulator sample is the pre-existing VLA prediction pipeline (`--prediction --send`), with an explicitly configured sample ID. Do not substitute GT.
- Keep runtime state STOPPED/STARTING/READY/RUNNING_SAMPLE/FAILED separate from the preview state machine. VALIDATED must never start simulation automatically.
- Use SimulatorClient/LocalSimulatorClient injected separately into create_app. The old Workflow IsaacClient remains disabled for web preview submission.
- Only the two fixed external script names may launch, with shell=False and backend-owned arguments. A fixed internal import-only probe is allowed, never a SimulationApp instance in diagnostics. APIs accept an empty action only; never accept browser commands, paths, scripts, or trajectories.
- Use WELD_SIM_LAUNCHER explicitly (.exe or Windows .bat/.cmd); WELD_SIM_PYTHON is a deprecated fallback. Never infer backend Python for Isaac. A backend-Python gate establishes ownership before invoking the configured Isaac launcher.
- For batch launchers use fixed System32/cmd.exe with /D /V:OFF /S /C, quoted launcher/runner paths, and no browser arguments. Reject expansion/control characters in these two paths. Transport script arguments as a JSON environment manifest, not through cmd or CALL quoting. Remove inherited PYTHONEXE overrides.
- WELD_SIM_SAMPLES_DIR maps to the original --samples-dir and supersedes --data-root. WELD_SIM_DATA_ROOT otherwise expects the original 3.개방데이터/1.데이터/Other hierarchy.
- Missing metadata requires explicit WELD_SIM_PREDICTION_FORMAT=legacy_npz. Validate exact H5/episode mapping, finite shapes/units, and GT resampled from H5 within 0.05 mm. Never align away mismatches, substitute GT, or modify original predictions.
- Generate only the four metadata fields verified in external welding_prediction.py. Byte-copy NPZ and record provenance hashes under this repo's .cache. Do not invent split/metrics or reuse stale solution NPZ files lacking mounted_fixture_v2.
- GET status must only read cached import diagnostics. A real import-only check is an explicit CLI operation. Automated tests use stub launchers; no heavy Isaac/GUI launch.
- Redirect queue and sample artifacts to .cache/simulator/sessions/<UUID>. Disable external Python bytecode writes. Do not replay an old queue on restart.
- Confirm READY only from the current process's exact queue-ready stdout message. A live PID or server.lock file alone is insufficient.
- Success requires exit=0, the matching result JSON state=done, and expected artifacts/report. Timeout or failure cancels owned processes and queued playback.
- Manage only owned process trees. Retain the exclusive runtime lease until cleanup succeeds. Windows uses a kill-on-close Job Object and a launch gate; never kill a discovered external PID.
- Windows compatibility for the server's fcntl.flock subset lives here, injected only into owned children. This does not establish compatibility with arbitrary Isaac versions or WSL locks.
- Use stubbed processes for automated tests; never start the heavy simulator/GUI in pytest or E2E. Follow docs/simulator.md for a separate manual integration check.

## Verification
From the root: `.\.venv\Scripts\python.exe -m pytest` and `.\.venv\Scripts\python.exe -m compileall -q backend`.
From frontend: `npm.cmd run build` and `npm.cmd run test:e2e` (requires the local Playwright Chromium browser and starts its own test servers).
Verify mask dimensions/binary values, instruction ordering, state rejection, downstream invalidation, dummy path direction, validation, and a full plan response. Add multi-region regression coverage for independent segments, skips/order, stable IDs/noise, VLA correspondence, rejection of merged paths, and no connecting pixels in the UI. Keep test storage inside temporary directories and never overwrite user scene data.
