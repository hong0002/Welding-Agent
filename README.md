# Welding Agent · Preview Studio

2026 경남 AI·SW 경진대회를 위한 Human-in-the-Loop 로봇 용접 시스템의 실행 가능한 MVP입니다.

**웹 출력은 2D 이미지 픽셀 기반 Preview trajectory입니다.** Assistant에서 자연어로 영역·방향·경로 생성을 지시할 수 있습니다. 별도 Simulator 패널에서 기존 외부 VLA 샘플을 실행·모니터링할 수 있습니다. 웹 경로는 시뮬레이터에 전달되지 않으며 물리 로봇 실행은 비활성입니다. 수동 Preview는 API key 없이 동작하며, GPT Assistant만 선택적으로 OpenAI API를 사용합니다.

```text
RGB 이미지 업로드 → Manual binary mask 확정 → 연결 영역 검출 → 명령/영역 선택
  → 영역별 Dummy Rough Segment → 영역별 Dummy VLA → Preview validation → 독립 경로 표시
```

Manual mask는 “어디를 용접할 것인가”를 전달하는 **2D visual conditioning**입니다. 3D로 자동 변환하지 않습니다. GPT는 명령 이해·tool 선택·고수준 orchestration만 담당하며 좌표를 생성하거나 로봇을 직접 실행할 수 없습니다.

## Welding Assistant

공식 OpenAI Agents SDK 0.22.3와 Responses API를 사용합니다. 기본 탭 **Assistant**에서 Brush → Chat → Enter로 지시하면 dirty mask를 자동 확정하고 기존 Workflow를 실행해 Canvas를 갱신합니다. 후속 메시지로 “두 번째 영역은 제외해줘” 같은 수정이 가능합니다. 대화는 SQLite에 보관하며 브라우저에는 session ID만 저장합니다.

프로젝트 루트 `.env`에 `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-5.6`, `WELD_AGENT_ENABLED=true`, `WELD_AGENT_MAX_TURNS=8`을 설정한 뒤 backend를 재시작하세요. 키는 backend의 이 파일에서만 읽고 frontend로 전달하지 않습니다. **수동 지시 / 디버그**, Path, Simulator, Console은 그대로 사용할 수 있습니다. 설정 없는 상태에서도 수동 기능은 동작합니다.

“방금 만든 경로 시뮬레이션해”는 연결 제한을 안내합니다. “기존 VLA 샘플 실행해”라는 명시적 요청만 기존 샘플 재생을 허용합니다. 계획 완료 후 자동 실행하지 않습니다.

상세 설정, 7개 도구, SSE/API, 실패 복구, 테스트 및 사람이 직접 실행하는 live smoke 명령은 [docs/agent.md](docs/agent.md)를 참고하세요. 자동 pytest/E2E에는 가짜 Runner/모델/Simulator를 주입하며 실제 OpenAI API나 Isaac GUI를 실행하지 않습니다.

## 빠른 시작 — Windows PowerShell

검증 환경: Python 3.12, Node.js 24, npm 11, Chrome. Python 3.12와 Node.js 22 이상을 권장합니다. 2D Preview에는 Docker, GPU, API key가 필요하지 않습니다. 선택적인 Simulator 실행에는 기존 Isaac 환경과 데이터가 필요합니다.

### 1. Backend 설치

프로젝트 루트에서 실행합니다. 기존 Python 환경을 사용할 수도 있으나, 프로젝트 전용 가상환경을 권장합니다.

```powershell
cd "D:\Research_and_Paper\2026경남AISW경진대회\code\Welding-Agent"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

현재 Windows/Python 3.12에서 테스트한 버전 조합을 그대로 설치하려면 마지막 명령 대신 다음을 사용합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
```

### 2. Backend 실행

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

- API: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- Swagger: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

가상환경 activation 없이 실행하므로 PowerShell execution policy를 변경할 필요가 없습니다. 기본 설정으로 바로 실행할 수 있습니다. 설정 변경이 필요하면 `.env.example`을 `.env`로 복사하고 `--env-file .env`를 uvicorn 명령에 추가합니다. `.env`는 Git에서 제외됩니다.

### 3. Frontend 설치 및 실행

**새 PowerShell 창**을 열고 실행합니다.

```powershell
cd "D:\Research_and_Paper\2026경남AISW경진대회\code\Welding-Agent\frontend"
npm.cmd ci
npm.cmd run dev
```

[http://127.0.0.1:5173](http://127.0.0.1:5173)을 엽니다. `npm.cmd`는 Windows의 `npm.ps1` 실행 정책 문제를 피합니다. 일반 터미널에서는 `npm install`, `npm run dev`도 사용할 수 있습니다. 두 서버는 각각 `Ctrl+C`로 종료합니다.

Vite는 `/api`를 `http://127.0.0.1:8000`으로 프록시합니다. Backend 포트를 변경했다면 프런트엔드를 시작하기 전에 `$env:VITE_API_PROXY_TARGET = 'http://127.0.0.1:새포트'`를 설정합니다. 프런트엔드 설정은 `frontend/.env.local`에도 둘 수 있습니다. 루트 `.env`가 Vite에 자동으로 로드되지는 않습니다.

## MVP 사용 방법

1. 상단 `Backend connected`를 확인합니다.
2. **RGB 업로드**로 PNG/JPEG/WebP를 선택하거나 **샘플 이미지로 시작**을 누릅니다. 샘플은 합성 금속판 이미지입니다.
3. **Brush**로 용접 영역을 그립니다. **Eraser**, **Undo**, **Clear**를 사용할 수 있고, Clear도 Undo로 되돌릴 수 있습니다. 브러시 크기는 원본 이미지 픽셀 단위입니다.
4. **Mask opacity**는 표시만 변경합니다. **마스크 확정**은 원본 해상도로 이진 PNG를 생성하여 백엔드에 저장합니다. 저장값은 배경 0, 선택 영역 255입니다.
5. `왼쪽에서 오른쪽으로 용접해` 또는 `오른쪽에서 왼쪽으로 용접해`를 입력하고 **Parse Instruction**을 누릅니다. `left to right` / `right to left`도 지원합니다. 방향이 없거나 모호한 입력, 제외 영역 요청은 오류로 반환합니다.
6. 마스크 확정 후 **Regions: N**과 각 **Region ID**를 확인합니다. 영역 체크박스를 해제하면 해당 영역을 제외합니다. 선택 변경 후에는 **Parse Instruction**을 다시 누릅니다. **Generate Weld Plan**을 누릅니다. 금색 점선은 Rough path, 민트색 실선은 Final VLA preview입니다. 체크박스로 각각 표시 여부를 바꿀 수 있습니다. 각 segment의 채워진 점은 경로 시작점입니다. 서로 떨어진 영역 사이에는 연결선을 그리지 않습니다.
7. `Preview geometry 통과`와 `VALIDATED` 상태를 확인합니다. **Preview JSON 저장**, **Binary mask**, **VLA overlay**로 결과를 확인할 수 있습니다.
8. 마스크를 편집하면 다시 확정하고 명령을 다시 분석해야 합니다. 명령만 바꿨다면 다시 Parse한 후 경로를 생성합니다. 이전 경로와 검증 성공 표시는 즉시 숨깁니다.

이미지는 최대 20 MiB / 12,000,000 픽셀 / 한 변 8192 픽셀입니다. JPEG EXIF 회전을 적용한 **정규화된 RGB 이미지**를 화면과 마스크의 공통 기준으로 사용합니다. 빈 마스크, 크기가 다른 마스크, 0/255 이외 값, 투명하거나 컬러인 마스크는 거부합니다. 브라우저의 불투명 RGBA PNG는 grayscale 여부를 확인한 뒤 L 모드로 저장합니다.

## 프로젝트 구조

```text
Welding-Agent/
├─ AGENTS.md                         개발 규칙과 역할 경계
├─ README.md
├─ .env.example
├─ backend/
│  ├─ main.py                        FastAPI, REST, CORS, artifact serving
│  ├─ schemas.py                     Pydantic 공통 계약
│  ├─ requirements.txt               허용 의존성 범위
│  ├─ requirements-lock.txt          검증한 Windows/Python 3.12 버전
│  ├─ orchestrator/
│  │  ├─ workflow.py                 교체 가능한 client 주입 및 pipeline
│  │  ├─ state_machine.py            순서 강제와 upstream 변경 처리
│  │  ├─ instruction_parser.py       InstructionParser + Dummy 구현
│  │  └─ region_selection.py         region ID 선택/순서/제외 검증
│  ├─ services/
│  │  ├─ storage.py                  PNG와 JSON 저장
│  │  ├─ mask_service.py             binary 검증, 독립 overlay
│  │  ├─ components.py               8-connected 영역 검출과 metadata
│  │  ├─ legacy_migration.py         v1 저장 job의 보수적 업그레이드
│  │  ├─ segmentation_client.py      SegmentationClient + Dummy
│  │  ├─ rough_path_client.py        RoughPathClient + Dummy
│  │  ├─ vla_client.py               VLAClient + Dummy
│  │  ├─ validation.py               TrajectoryValidator + Dummy
│  │  ├─ isaac_client.py             웹 preview 전송은 비활성
│  │  ├─ simulator_client.py         기존 샘플 launcher/monitor, 별도 상태
│  │  ├─ simulator_process.py        배치/executable 실행과 Windows Job 관리
│  │  ├─ simulator_diagnostics.py    명시적 import 검사 결과 캐시
│  │  └─ legacy_prediction_adapter.py H5 검증 후 누락 metadata를 cache에 생성
│  ├─ simulator_smoke.py             GUI 없는 명시적 Isaac import 검사
│  ├─ simulator_bootstrap.py         Job 소유권 설정 후 launcher 실행
│  ├─ simulator_runner.py            프로세스 소유권 설정 후 기존 스크립트 실행
│  ├─ simulator_compat/fcntl.py      Windows 전용 외부 서버 flock 호환
│  └─ storage/{scenes,masks,trajectories,jobs}/
├─ frontend/
│  ├─ src/{App,MaskCanvas,RegionSelector,SimulatorPanel}.tsx
│  ├─ src/{api,mask,types}.ts         API, 원본 크기 export, 타입
│  ├─ src/styles.css
│  ├─ playwright.config.ts
│  └─ e2e/{workflow,simulator}.spec.ts
├─ tests/                            pytest
└─ docs/{architecture,simulator}.md
```

## API

`upload` 응답에서 생성된 `id`가 `job_id`입니다. 모든 변경 API는 현재 `WeldJob` 전체를 반환합니다. 이미지 URL은 `/api/...` 상대 경로입니다.

| Method | Path | Input / purpose |
|---|---|---|
| GET | `/api/health` | 연결, dummy mode, 실행 비활성 상태 |
| POST | `/api/scenes/upload` | multipart `file` → 새 job 및 RGB scene |
| POST | `/api/masks/manual` | multipart `job_id`, `file`, optional `min_component_area` → mask/regions 확정 |
| POST | `/api/masks/automatic` | JSON `job_id`, optional `min_component_area` → **합성 중앙 띠** Dummy mask |
| POST | `/api/instructions/parse` | JSON `job_id`, `instruction`, optional `region_selection` |
| POST | `/api/weld/plan` | JSON `job_id` → rough/refine/validate |
| GET | `/api/weld/{job_id}` | 저장된 job 조회 |
| POST | `/api/weld/{job_id}/rough` | `INSTRUCTION_READY`에서만 실행 |
| POST | `/api/weld/{job_id}/refine` | `ROUGH_PATH_READY`에서만 실행 |
| POST | `/api/weld/{job_id}/validate` | `VLA_REFINED`에서만 실행 |
| GET | `/api/scenes/{scene_id}/image` | 정규화 RGB PNG |
| GET | `/api/masks/{mask_id}/image` | 원본 해상도 L-mode PNG |
| GET | `/api/masks/{mask_id}/overlay` | 별도 RGB conditioning preview |

순서 오류는 `409`, 데이터 오류는 `422`, 알 수 없는 ID는 `404`, 파일 용량 초과는 `413`입니다. 이미 `VALIDATED`인 job에 plan을 재요청하면 같은 결과를 반환합니다. 중간 상태에서 plan을 재요청하면 남은 단계부터 진행합니다.

예시 plan 요청:

```json
{"job_id": "업로드 응답의 id"}
```

경로의 공통 필드:

```json
{
  "coordinate_space": "image_pixel",
  "units": "px",
  "is_robot_executable": false,
  "kind": "final_preview",
  "generator": "dummy-independent-segment-resample-smooth",
  "segments": [
    {"segment_id": 0, "region_id": 0, "mode": "weld", "points": [{"x": 20.0, "y": 50.0}]},
    {"segment_id": 1, "region_id": 1, "mode": "weld", "points": [{"x": 120.0, "y": 90.0}]}
  ]
}
```

## 다중 영역과 호환성 (schema v2)

- 하나의 mask에 서로 떨어진 영역이 있으면 **영역마다 하나의 독립 weld segment**를 만듭니다. 자동 travel 경로는 만들지 않습니다.
- `Mask.regions`에는 `region_id`, `pixel_area`, `bounding_box`(최대 좌표 포함), `centroid`가 저장됩니다. 8방향으로 접한 픽셀은 같은 영역입니다.
- ID는 같은 마스크에서 안정적이며, 이미지 위→아래/왼쪽→오른쪽 순으로 최초 픽셀이 등장하는 순서로 부여합니다. 면적 필터 이전에 부여하므로 ID에 빈 번호가 생길 수 있습니다. 마스크를 편집하면 재검출하므로 이전 ID를 계속 사용하지 마세요.
- 기본 최소 면적은 **16픽셀**입니다. `WELD_MIN_COMPONENT_AREA` 환경 변수 또는 mask API의 `min_component_area`로 변경할 수 있습니다. 원본 0/255 PNG는 보존하고 작은 영역을 planning에서 제외합니다. 모든 영역이 제거되면 오류를 반환합니다.
- 기존 endpoint와 upload → mask → parse → plan 흐름은 유지합니다. 응답은 `schema_version: 2`, `coordinate_space: "image_pixel"`, `segments[]` 구조입니다. 전역 `points` 배열은 제공하지 않습니다.
- v1 저장 job은 조회 시 `<job_id>.legacy-v1.json`으로 원본을 백업하고 RGB/mask를 보존합니다. 기존 경로와 검증은 무효화하고 `MASK_READY`에서 명령을 다시 분석하도록 합니다. 과거 마스크는 최소 면적 1로 재분석해 기존 입력 픽셀을 보존합니다. 업그레이드 후 브라우저를 새로고침하세요.

명령 파싱 API의 region 제어 예시:

```json
{
  "job_id": "업로드 응답의 id",
  "instruction": "왼쪽에서 오른쪽으로 용접해",
  "region_selection": {"start_region": 2, "region_order": [2, 0], "skip_regions": [1]}
}
```

`region_order` 생략 시 각 영역 중심의 x 좌표를 direction에 맞춰 정렬합니다. 명시하면 제외되지 않은 모든 ID를 정확히 한 번씩 넣어야 합니다. `start_region`은 지정 순서의 첫 ID와 일치해야 합니다. 알 수 없는 ID, 중복, 모든 영역 제외는 거부합니다. 방향은 각 segment 내부의 점 순서에도 적용됩니다.

## 테스트와 빌드

루트에서:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp=.cache/pytest
.\.venv\Scripts\python.exe -m compileall -q backend
```

Frontend에서:

```powershell
npm.cmd run build
```

실제 브라우저 E2E 테스트는 별도 포트 **8001 / 5174**에서 테스트 서버를 띄우고 종료합니다. 테스트 저장소는 `.cache/e2e-storage`이며 일반 `backend/storage`를 사용하지 않습니다.

이미 Chrome이 설치된 Windows에서는 다음처럼 실행할 수 있습니다.

```powershell
cd frontend  # 현재 루트에 있는 경우에만 실행
$env:WELD_TEST_BROWSER = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$env:TEMP = Join-Path (Split-Path (Get-Location).Path -Parent) ('.cache\browser-temp-' + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
npm.cmd run test:e2e
```

Chrome 경로가 다르면 `WELD_TEST_BROWSER`를 변경합니다. 다른 Python 환경은 `WELD_TEST_PYTHON`으로 지정합니다. 설치된 브라우저가 없으면 프로젝트 내부에 Playwright Chromium을 설치할 수 있습니다.

```powershell
Remove-Item Env:WELD_TEST_BROWSER -ErrorAction SilentlyContinue
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Split-Path (Get-Location).Path -Parent) '.cache\playwright'
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

Backend 테스트는 기존 Preview 검증과 Simulator 상태·프로세스 수명주기 검증을 포함합니다. 실제 Isaac/GPU는 테스트에서 실행하지 않습니다. E2E는 기존 이미지/마스크/독립 segment 흐름, 390px 화면, Simulator 버튼·상태·오류·설정 안내, Preview 검증 시 자동 실행이 없음을 검사합니다. 화면 캡처는 `frontend/test-results/`에 생성됩니다. Playwright 실행 결과는 `test-results/runs/<timestamp>`에 보존하며, Windows의 이전 결과/임시 캐시 정리 문제를 피하기 위해 실행마다 새 임시 폴더를 사용합니다. 현재 설치 조합의 Starlette TestClient는 httpx 관련 deprecation warning 1개를 출력하며 테스트 결과에는 영향이 없습니다.

이 Windows 실행 환경에서 Vite의 기존 `dist` 자동 정리 단계가 Node 프로세스를 종료시키는 현상이 확인되어 `emptyOutDir: false`를 설정했습니다. `index.html`과 새 빌드는 정상 생성되며, 이전 해시 이름의 asset은 남습니다. 깨끗한 배포 산출물이 필요하면 새 출력 디렉터리를 사용하세요. Konva를 포함한 JS 번들은 약 590 kB이며 Vite가 크기 경고를 출력하지만 빌드는 성공합니다.

## Simulator 실행 — 기존 VLA 샘플

Windows launcher와 legacy prediction adapter 테스트를 포함합니다. 실제 Isaac GUI 검증은 아래 설정 후 별도로 수행합니다.
검증 결과(2026-09-28): **pytest 136개, E2E 7개 통과**, production build·compileall·pip check 성공입니다.

Validation 다음의 **Simulator** 패널은 별도 런타임입니다. 외부 `../simulator`는 read-only이며, 현재 웹의 `image_pixel` / `is_robot_executable=false` Dummy 경로를 전송하지 않습니다. 기존 `run_welding_sample.py --send --prediction`의 입력과 학습된 export를 그대로 사용합니다. 물리 로봇 실행은 비활성입니다.

1. 이 PC에서는 `D:/isaacsim/python.bat`가 Isaac 환경을 구성하고 `kit.exe`를 실행합니다. Anaconda나 bare python.exe를 대신 지정하지 않습니다.
2. `.env`에 아래 실제 경로를 작성했습니다. `.env.example`은 다른 환경용 설정 설명입니다. `WELD_SIM_PYTHON`은 이전 executable 설정을 위한 optional fallback입니다.
3. Backend를 `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --env-file .env --host 127.0.0.1 --port 8000`으로 재시작합니다. 실제 GUI 사용 중에는 `--reload`를 생략하세요. Reload/종료 시 소유한 simulator도 정리됩니다.
4. **Start Simulator → READY → Run Existing Welding Sample → SUCCEEDED → Stop Simulator** 순으로 사용합니다. Preview가 VALIDATED되어도 자동으로 실행되지 않습니다.

API는 `GET /api/simulator/status`, `GET /api/simulator/logs`, `POST /api/simulator/start`, `POST /api/simulator/run-sample`, `POST /api/simulator/stop`입니다. POST는 빈 JSON `{}`만 받으며 임의 명령·경로·trajectory를 받지 않습니다.

시작은 기존 `[READY]` 로그로 확인합니다. 샘플은 준비 프로세스 exit=0뿐 아니라 matching queue result=done과 출력 파일까지 확인합니다. 중복 실행, 준비 전 실행, 타임아웃을 처리하고 직접 시작한 프로세스 트리만 종료합니다. 출력은 `.cache/simulator/sessions/<UUID>`에 남습니다. Windows의 외부 `fcntl` 사용은 Welding-Agent 내부 호환 모듈로 처리합니다.

```dotenv
WELD_SIM_ROOT=D:/Research_and_Paper/2026경남AISW경진대회/code/simulator
WELD_SIM_LAUNCHER=D:/isaacsim/python.bat
WELD_SIM_SAMPLE_ID=L_PR_03_0001
WELD_SIM_SAMPLES_DIR=D:/연구/sim/Datase/other_data/Other/Other/로봇티칭데이터
WELD_SIM_PREDICTION_ROOT=D:/연구/sim/welding_validation_all
WELD_SIM_PREDICTION_FORMAT=legacy_npz
```

현재 데이터 구조는 `--data-root`가 요구하는 `1.데이터/Other` 구조와 다르므로 기존 `--samples-dir` 옵션을 사용합니다. Windows에서 형제 OBJ 폴더를 찾는 기존 fallback을 사용하도록 `로봇티칭데이터`까지 지정합니다. 원본 prediction에는 metadata가 없어, H5와 GT를 비교한 후 `.cache`에 원본 NPZ의 바이트 복사본과 코드에서 확인한 네 metadata 필드만 생성합니다. GT/H5 최대 오차는 약 0.000098 mm로 기존 허용치 0.05 mm 이내입니다. 원본 파일은 수정하지 않습니다.

`.\.venv\Scripts\python.exe -m backend.simulator_smoke --env-file .env`로 실제 배치 실행기의 **import-only 검사**를 할 수 있습니다. 이 PC에서는 Isaac·NumPy·SciPy·h5py import가 통과했습니다. status와 UI의 환경 진단은 저장된 결과만 읽으며 프로세스를 실행하지 않습니다.

**실제 Isaac GUI는 자동 검증에서 실행하지 않았습니다.** 원본 `prediction_index`/`prediction_targets`로 캐시 export 계약을 확인했지만 GUI/IK/Kit 호환성은 수동 재생으로 확인해야 합니다. 정확한 H5 경로, metadata schema, 배치 실행 설계, 수동 테스트 명령은 [Simulator 안내](docs/simulator.md)에 있습니다.

## 현재 범위와 다음 연결 작업

- **Segmentation:** 실제 검출 없이 중앙 띠를 반환합니다. UI의 기본 입력은 manual mask이며, 자동 마스크는 adapter/API 검증용입니다.
- **Parser:** 두 방향을 인식하는 규칙 기반 Dummy입니다. 일반적인 자연어 의미·부정문·자연어 제외 구문·복합 작업은 지원 범위가 아닙니다. region ID 기반 제외/순서는 체크박스 또는 구조화된 API 필드로 지정합니다.
- **Rough Path:** 각 연결 영역에서 실제 foreground 픽셀을 열별로 최대 32개 샘플링합니다. 영역마다 독립 segment를 생성합니다. 오목하거나 가지가 있는 단일 영역 내부의 최적 경로 탐색은 구현하지 않았습니다.
- **VLA:** 각 Rough segment를 독립 보정하고 segment/region ID를 보존합니다. 두 점 이상인 segment를 **48개 이상의 점**으로 재샘플링하고 완만하게 평활화합니다. 단일 점은 그대로 유지합니다. 학습된 모델이 아닙니다.
- **Validation:** 빈 segment/point, NaN/Inf, 이미지 경계, region 대응/순서/중복, component 근접성을 검사합니다. 각 segment 점의 80% 이상이 자기 영역 안 또는 반올림 좌표 주위 2px 사각 근방에 있어야 합니다. 복잡한 형상의 Dummy 경로는 이 검사에서 거부될 수 있습니다. 모든 보간 선분의 마스크 내부 체류, 용접 품질, 로봇 workspace, collision, joint limits는 보장하지 않습니다.
- **Simulator:** 외부 read-only 프로젝트의 기존 VLA prediction 샘플만 실행하는 launcher/monitor입니다. 웹 Preview 전송은 연결하지 않았으며 물리 로봇 실행 endpoint는 없습니다.

실제 모델은 각 Protocol을 구현하고 `Workflow`에 주입합니다. Remote VLA에는 RGB PNG, binary mask PNG, rough trajectory JSON, 원문 언어, structured instruction을 보내도록 adapter를 구현하면 됩니다. OpenAI orchestrator도 이 상태 머신을 그대로 따릅니다.

실제 로봇 연동은 별도의 좌표계·calibration·robot trajectory schema·simulation 검증·사용자 승인 흐름을 먼저 설계해야 합니다. 2D mask는 계속 visual conditioning으로 보존합니다. 자세한 계약은 [architecture.md](docs/architecture.md)에 있습니다.

이 MVP 저장소는 **단일 백엔드 프로세스**용입니다. `--workers`를 늘리지 마세요. 인증 없는 로컬 개발용이므로 기본 bind는 `127.0.0.1`입니다. 백엔드 job/artifact는 재시작 후에도 보존되지만, 현재 프런트엔드의 그리기 이력과 선택된 세션은 새로고침 시 초기화됩니다. 저장된 job은 ID로 REST 조회할 수 있습니다. 이미지 교체 시 새 job을 만들며 과거 artifact는 자동 삭제하지 않습니다.
