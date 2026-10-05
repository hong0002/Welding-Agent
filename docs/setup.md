# Setup

## Environments

Run commands from the repository root. Create a backend `.venv` and install `backend/requirements.txt`. Create a separate native Python 3.12 environment; put its absolute `python.exe` path in `WELD_NATIVE_PYTHON`. This is backend-owned configuration, never a browser argument. Isaac requires its own explicitly configured launcher; backend/native Python is not inferred as the Isaac launcher.

The audited native stack uses NumPy 1.26.4, SciPy 1.16.0, trimesh 5.1.0, rtree 1.4.1 and `faiss-cpu==1.8.0.post1`. Install the small module requirements in `vlm_segment2`, `vlm_trajectory3`, `vlm_final_gpt2`, and `requirements-native-release.txt` into the native environment; retain your CUDA-compatible PyTorch/transformers installation. Do not install backend NumPy>=2 requirements into the audited native environment. No setup script downloads encoders, builds indexes or launches inference.

Offline simulator preparation additionally uses repository-owned dependencies:

```powershell
& "PATH_TO_NATIVE_PYTHON" -m pip install --no-deps --target .cache/simulator2/python-deps -r requirements-simulator2-offline.txt
```

## Backend-owned configuration

Copy `.env.example` to `.env` and edit it as UTF-8. Set:

- `OPENAI_API_KEY`: backend only; never put it in frontend/VITE variables.
- `WELD_DATASET_ROOT`: `3.개방데이터` containing both NIA RGB/labels and teaching H5/OBJ.
- `WELD_NATIVE_PYTHON`: native Python executable.
- `WELD_SIM_LAUNCHER`: installed Isaac Python launcher (for example the installation's `python.bat`).
- `WELD_GPT2_ENCODER_CACHE`: existing HF hub cache containing both encoders; alternatively prepare `.cache/model-encoders/hub`.
- Native Mask/Rough service settings: `WELD_NATIVE_SSH_ALIAS`, `WELD_NATIVE_REMOTE_ROOT`, `WELD_NATIVE_REMOTE_PYTHON`, `WELD_NATIVE_YOLO_PYTHON`. Configure SSH credentials outside this repository. Final uses LOCAL retrieval and does not require a resident daemon.

Leave source root overrides empty to select fixed `modules/` defaults. Native config templates in `configs/` retain the actual Windows model/reasoning/retrieval policies. `scripts/configure_release.py --sample-id SAMPLE_ID` resolves exact 9-view identity and writes only ignored `.cache/native-integration/configs` files. It refuses to overwrite differing existing configs and does not modify `.env`, original source, data, index or models.

The simulator source can remain in `modules/simulator_final` after adding the external assets documented below, or `WELD_SIM_FINAL_ROOT` can name a complete separately installed copy. Native prediction-only defaults do not require a RICL baseline. An explicit backend switch to `dataset_stp` is available only when its separate source/assets are configured; there is no automatic fallback.

## Start

Start `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` with the backend environment. In `frontend`, run `npm.cmd ci` then `npm.cmd run dev`. Check `/api/health` and `/api/simulator/status`; missing external assets are expected until operator setup is complete. Session/history initialization uses relative `/api` paths through the Vite proxy.

## Offline verification

```powershell
.\.venv\Scripts\python.exe -m compileall -q backend
.\.venv\Scripts\python.exe -m pytest tests/test_release_layout.py tests/test_gpt2_trajectory.py tests/test_simulator_final_client.py
cd frontend
npm.cmd run build
```

E2E uses `tests.agent_e2e_app` and fake transports only. Set `WELD_TEST_PYTHON` and, if needed, `WELD_TEST_BROWSER` to an installed Chromium/Chrome executable; `npm.cmd run test:e2e` never requests production OpenAI/Isaac.
