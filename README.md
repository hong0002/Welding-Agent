# Welding Agent · Preview Studio

현재 표시 정책은 [Visualization first](docs/visualization-first.md)입니다. 검증·승인 실패 결과도 raw viewer에서 확인할 수 있고, upstream 수정 이전 결과는 명시적인 이전 결과 viewer에 보존합니다. `GET /api/weld/{job_id}/model-outputs`는 표시·검증·승인·simulation·robot 상태를 분리합니다. `POST /api/simulator/geometry-preview`는 renderable raw XYZ를 owned Isaac viewport에서 선으로 표시하며 공작물 정렬·IK·robot playback을 수행하지 않습니다. 기존 엄격한 Robot admission은 유지합니다.

`dataset_stp`를 exact sample H5/OBJ + native `--layout stp` 방식으로 연결했습니다.
기존 exact STEP 차단 요구는 제거했고, B_PP_03_0006 원본 VLA 9점을 보존한
Path/Robot offline preflight가 통과했습니다. 이 sample-scene Robot의 실제 Isaac smoke는 아직 실행하지 않았으며
root `.env`는 유지했습니다. [native contract·30-family 범위·설정/rollback·수동 smoke](docs/simulator-stp-integration.md).
별도 Geometry Preview는 기존 상대좌표 raw artifact로 Isaac 실행과 웹 최신 캡처 표시를 확인했습니다. [검증 범위와 남은 live smoke](docs/visualization-first.md).


Segment2의 기존 YOLO 결과를 9-view Canvas의 파란 bbox/label로 표시합니다. `YOLO Objects`
toggle, view별 thumbnail count, Inspector 요약을 제공하며 마스크·경로 입력과 독립적입니다.
재추론 없이 현재 job의 native artifact만 검증해서 읽습니다.
[표시 API·native schema·좌표·offline replay 감사](docs/yolo-web-visualization.md).

`WELD_SIM_BACKEND=dataset_v2` candidate adapter를 추가했습니다. 실제 B_PP current VLA 원본9점과
native playback package가 offline PASS이며, 30개 family 대표 scene 중29개 PASS/C_PP_03_0001 nonfinite FAIL입니다.
기본값은 legacy입니다. B_PP_03_0006 GUI smoke는 P0 완료 후 capture에서 중단됐으며,
dataset_v2의 capture를 선택적 진단으로 분리하는 offline 수정이 완료됐습니다.
[capture 진단/수정/수동 확인](docs/simulator2-capture-fix.md), [simulator2 contract/전체 결과/전환과 rollback](docs/simulator2-integration.md).

Current VLA diagnostic preview는 family policy registry로 exact query H5/OBJ를 resolve합니다.
B_PP는 원본 9점 XYZ의 **Path Preview Ready / Robot Preview Pending**이며, 기존 audited
B_PR robot preview와 existing sample replay gate는 유지합니다. [Policy/실제 B_PP offline 검증](docs/family-preview-policy.md).

2026 경남 AI·SW 경진대회를 위한 Human-in-the-Loop 로봇 용접 시스템의 실행 가능한 MVP입니다.

Assistant 대화는 Agent 상태 확인 → 세션 복원/POST `{}` 생성 → history 조회로 연결합니다.
404/410 세션은 자동 교체하고 일시 오류는 기존 대화를 보존합니다. Agent 기본 loopback Origin은
5173/5174를 지원하며 명시적 허용 목록이 우선합니다. 연결 실패는 원인 코드와 재연결 버튼으로
표시합니다. [API contract·진단·Backend 재시작 후 확인](docs/agent-session-contract.md).

Canvas 경로는 **2D 이미지 픽셀 Preview trajectory**입니다. Dataset 장면은 별도로 NativeRough3D의 2D guidance와 승인 F mask를 Guided VLA에 전달하고, 원본 좌표계의 9점 XYZ 예측을 `VLA_READY` 요약으로 저장합니다. 물리 로봇 실행과 validated fixture gate는 blocked입니다. Simulator 탭에는 현재 job의 XYZ를 사용하는 별도 **VLA 시뮬레이션 미리보기 / Path Preview** 버튼이 있습니다. 기존 외부 VLA 샘플 재생과 Dummy 수동 Preview는 유지합니다. 선택적인 GPT Assistant와 native Segment/Rough 모드는 OpenAI API를 사용합니다.

```text
RGB 이미지 업로드 → Manual / VLM binary mask → 연결 영역 검출 → 명령/영역 선택
  → 영역별 Dummy / VLM Rough Segment → 영역별 Dummy VLA → Preview validation → 독립 경로 표시
```

Manual mask는 “어디를 용접할 것인가”를 전달하는 **2D visual conditioning**입니다. 3D로 자동 변환하지 않습니다. GPT는 명령 이해·tool 선택·고수준 orchestration만 담당하며 좌표를 생성하거나 로봇을 직접 실행할 수 없습니다.

Dataset sample ID 또는 원본 `<sample_id>_<view>_Color.png` 업로드 → canonical 9 views
`B/F/L/R/S1/S2/S3/S4/T` → Native Segment F/R/S4 → 사람이 F 승인 → 지시 →
configured NativeRough3D (`vlm_trajectory2` / `vlm_trajectory3`) → Canvas 2D guidance → **Guided VLA 실행** → `VLA_READY`.
원본 이미지 업로드는 filename과 SHA-256이 모두 일치해야 나머지 8장을 연결합니다.
view별 편집·승인 상태를 유지하며, 현재 검증된 Guided 요청은 **F-only**입니다.
R/S4는 웹 검토 artifact로 보존합니다. 미정합 3D reference는 업로드하지 않습니다.
실제 HTTP는 이 명시적 버튼, 사용자 실행 의도가 확인된 `run_guided_vla()` 또는
operator CLI `run --live`에서만 수행합니다. 자동 테스트는 모두 offline입니다.
Segment2와 Trajectory3의 **모델 출력 표시와 downstream 검증을 분리**합니다.
`raw_segment_output`은 accepted mask와 별도이며, `native_output.model_output`은 계약·provenance
오류에도 렌더링 가능한 원본 좌표를 보존합니다. 검증 통과는 실선, raw는 점선, partial은
짧은 점선으로 표시합니다. 잘못된 점은 생략하고 그 지점에서 선을 끊습니다. 다른 sample의
출력은 현재 Canvas에 겹치지 않고 diagnostic panel에서만 보여줍니다.
Guided VLA·Simulator에는 기존 validated/PASS·승인·immutable proof gate가 그대로 적용됩니다.
Raw 마스크는 **Raw 마스크 검토·수정 → Brush/Eraser → 마스크 확정 · F**로 명시적으로 검토합니다.
좌표/순서를 보정하거나 새로 만들지 않습니다. [표시 계약·API·회귀 검증](docs/model-output-display.md)을 참고하세요.
설정·API·사용 순서·검증 보고는 [docs/module-integration.md](docs/module-integration.md),
기존 CLI 계약은 [docs/guided-vla.md](docs/guided-vla.md)를 참고하세요.

현재 VLA preview는 `POST /api/simulator/preview-current-vla`에 `job_id`만 전달합니다.
backend가 현재 artifact와 immutable package를 해석하며 `WELD_SIM_SAMPLE_ID`는 사용하지 않습니다.
현재 지원되는 diagnostic placement는 audit된 `B_PR_03_0001`의 정확한 H5/OBJ입니다.
`B_PR_TOOL_CLEARANCE_FAIL`, `fixture_ready=false`, `physical_robot_executable=false`는 유지됩니다.
Robot Preview는 native URDF IK/FK의 9개 포즈를 순서대로 보여주는 kinematic visual이며 physics/timeline을 실행하지 않습니다.
실제 GUI smoke는 DAE reader 오류로 실패했고 reader 수정 후 offline 검사만 통과했습니다.
최종 상태와 다음 실행 절차는 [docs/current-vla-preview.md](docs/current-vla-preview.md)를 확인하세요.

## Welding Assistant

공식 OpenAI Agents SDK 0.22.3와 Responses API를 사용합니다. 기본 탭 **Assistant**에서 Brush → Chat → Enter로 지시하면 dirty mask를 자동 확정하고 기존 Workflow를 실행해 Canvas를 갱신합니다. 후속 메시지로 “두 번째 영역은 제외해줘” 같은 수정이 가능합니다. 대화는 SQLite에 보관하며 브라우저에는 session ID만 저장합니다.

프로젝트 루트 `.env`에 `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-6-luna`, `WELD_AGENT_REASONING_EFFORT=low`, `WELD_AGENT_ENABLED=true`, `WELD_AGENT_MAX_TURNS=8`을 설정한 뒤 backend를 재시작하세요. 키는 backend의 이 파일에서만 읽고 frontend로 전달하지 않습니다. **수동 지시 / 디버그**, Path, Simulator, Console은 그대로 사용할 수 있습니다. 설정 없는 상태에서도 수동 기능은 동작합니다.

“방금 만든 경로 시뮬레이션해”는 연결 제한을 안내합니다. “기존 VLA 샘플 실행해”라는 명시적 요청만 기존 샘플 재생을 허용합니다. 계획 완료 후 자동 실행하지 않습니다.

상세 설정, 도구, SSE/API, 실패 복구, 테스트 및 사람이 직접 실행하는 live smoke 명령은 [docs/agent.md](docs/agent.md)를 참고하세요. 자동 pytest/E2E에는 가짜 Runner/모델/Simulator를 주입하며 실제 OpenAI API나 Isaac GUI를 실행하지 않습니다.

9-view 채팅은 `B_PR_03_0001 불러와` → `용접할 부분 찾아줘` → 사람이 **마스크 확정 · F** →
`왼쪽에서 오른쪽으로 용접해` → `VLA 실행해` 순서입니다. 명시적 검출 요청은 승인 전에
`detect_weld_mask()`로 configured Segment를 실행하며, 새 AI 마스크를 자동 승인하지 않습니다.
기존 마스크는 `마스크 다시 찾아줘` / `재검출해줘` 요청에만 교체합니다. 이전 파일과 lineage를
보존하고 새 승인을 요구하며 Rough/VLA를 무효화합니다. Segment2/Trajectory3 계약 비교,
검증 결과와 rollback 설정은 [native stack migration](docs/native-stack-migration.md)을 참고하세요.

## Segment / Rough 모델 어댑터

`native` 모드는 검증된 `NativeSegmentClient` / `NativeRoughClient`를 Workflow에 주입합니다. 고정된 py3_12 Python으로 외부 원본 `mask.py` / `cot.py`를 `shell=False` 실행하고 native SSH retrieval과 artifact format을 유지합니다. 외부 저장소는 읽기 전용이며 출력은 Welding-Agent `.cache/native-models`에 생성합니다. `real`은 native의 이전 설정 이름이고 기본값은 계속 Dummy입니다. [설정·승인 계약·9-view 규칙](docs/models.md)을 참고하세요.

명시적 version 설정은 Segment `native_v1` / `native_v2`, Rough3D `native_3d_v2` /
`native_3d_v3`입니다. 새 모드는 `vlm_segment2` / `vlm_trajectory3` 원본을 사용합니다.
Trajectory3의 누락된 shared detector 경로는 고정 launcher가 실제 Segment2 native 모듈을
연결합니다. 승인 session에는 검증된 native YOLO detection을 byte-copy하여 재사용합니다.
기존 clients와 `baseline_2d`를 유지하며 자동 fallback은 하지 않습니다. `.env.example`은
Dummy/기존 opt-in 설정을 유지하고, 로컬 production 전환은 모든 migration gate 통과 후에만 합니다.

Native AI 마스크는 Canvas에서 **승인 대기**로 표시됩니다. **마스크 확정** 후 현재 binary mask에서 native Rough 입력 세션을 만듭니다. Brush/Eraser 수정은 `manual_edited`로 저장되고 이전 계획을 무효화합니다. 기존 native polyline을 현재 binary mask로 clipping하며 중심선이나 rough points를 새로 생성하지 않습니다. 기존 선 밖에 새로 그린 영역 등 표현할 수 없는 편집은 모델 호출 전에 거절합니다.

Native launcher는 parity와 동일한 setup 60초 / retrieval 120초 / 각 GPT stage 240초 watchdog과 전체 제한(기본 900초)을 적용합니다. SDK timeout/retry는 변경하지 않습니다. `.cache/native-models/diagnostics`에 UUID별 JSONL과 허용된 진행·오류 요약만 담은 `.native.log`를 별도 보존합니다. 2026-09-30 controlled Segment 1회는 F/R/S4와 result.json 생성 후 약 42초, exit=0으로 완료됐습니다. Canvas 승인 → Native Rough live 검증은 별도 단계입니다.

초기 fresh F 승인 후 Rough 실행은 5-sample mirror에 `B_RS_03_0005` 라벨이 없어 실패했습니다. 이후 실제 압축 해제된 Windows dataset으로 전환하고 **기존 승인 그대로 Rough 1회**를 실행해 `NATIVE_SEGMENT_ROUGH_LIVE_E2E_PASS`를 확인했습니다(61.08초, exit=0, 1 segment / 9 points, `ROUGH_PATH_READY`). 현재 Segment `mask.dataset_root`는 `D:/용접로봇데이터/42.용접로봇 행동 생성 데이터/3.개방데이터/2.데이터(NIA)`, Rough `data.root`는 그 상위 `3.개방데이터`입니다. Segment 재호출·재승인·VLA·Isaac·Simulator 실행 없이 완료했으며, [진단·산출물 기록](docs/models.md)에 두 시도의 결과를 보존했습니다.

**Native 계획은 Rough에서 종료하며 VLA를 호출하지 않습니다.** Dummy 모드는 기존 Dummy VLA preview를 유지합니다. Experimental image-only worker와 skeleton adapter는 `experimental`로 명시한 경우에만 남아 있고 native 경로에서 사용하지 않습니다. 현재 로컬 `.env`는 native로 설정되어 있으므로 서버를 재시작하면 적용됩니다. 단일 프로세스 연구 MVP이며 production/multi-worker 안전성을 의미하지 않습니다.

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

## Simulator 미리보기 — 현재 Web VLA

권장 흐름은 **Dataset → Segment2 → F mask 검토·승인 → Trajectory3 2D guidance →
Guided VLA 3D prediction → Simulator**입니다. 상단 PLAN은 Rough / VLA ready이며,
사용하지 않는 Validate navigation은 제거했습니다. Backend의 geometry/integrity
검증과 기존 상태·route는 유지합니다.

Simulator 패널에서 **현재 VLA 경로 보기 (Path Preview) → 필요 시 로봇 준비 확인
(Offline) → VLA 로봇 미리보기 (Robot Preview) → 시뮬레이터 중지** 순으로 사용합니다.
현재 상태의 권장 버튼을 강조하고 준비되지 않은 이유를 표시합니다. Dataset backend는
이전 샘플 replay controls를 숨기며, legacy backend에서만 닫힌 고급 항목으로 제공합니다.

`dataset_stp`의 Path/Robot은 동일한 **빨간 연결 선**으로 원본 VLA 9 XYZ 경로를
표시합니다. 선폭은 6 mm/constant이며 중간 점 marker는 기본 OFF입니다. GT는 녹색 reference입니다. Robot의 native derived
playback과 simulator-policy orientation은 별도입니다. 원본 prediction/metrics는 변경하지 않습니다.

웹의 **시뮬레이터 화면**은 Robot 재생 중 viewport MJPEG Live View를 우선 표시합니다.
목표 8 FPS, 최대 1280×720, JPEG quality 80이며 desktop 화면을 캡처하지 않습니다.
P0/P4/P8/경로 상세 Latest capture와 확대 기능도 유지합니다. Job/artifact/request/session 및
승인 proof가 일치할 때만 표시하며 중지·실패·작업 변경 시 숨깁니다. 캡처/stream 실패는
Robot 재생 실패와 분리합니다. Inspector 모델 상태는 기본 접힘이며 Assistant 공간을 확보합니다.
Live API·기존 descriptor 갱신·수동 검증은 [Live View 안내](docs/simulator-live-view.md)를 참고하세요.
자세한 API·설정 후보·기존 artifact upgrade·rollback은 [Preview UX 안내](docs/simulator-preview-ux.md)에 있습니다.

### 기존 샘플 replay — 호환 기능

Current Web VLA Preview와 기존 샘플 재생은 설정 검사를 분리합니다.
`GET /api/simulator/status`의 `existing_replay.configured/errors`는 기존 sample ID·데이터·prediction root와 launcher를 검사합니다.
`current_preview.configured/configuration_errors/configuration_codes`는 launcher·simulator source/assets·감사된 B_PR 진단 자산을 검사합니다.
현재 job·VLA artifact·immutable package는 Preview POST에서 다시 검증하며, replay의 `WELD_SIM_SAMPLE_ID`와 `WELD_SIM_PREDICTION_ROOT`는 사용하지 않습니다.
기존 top-level `configured`는 호환성을 위해 runtime 시작 가능 여부 의미를 유지합니다. Current Preview 버튼은 `current_preview.configured`를 사용합니다.

Simulator 설정은 프로젝트 루트 `.env`를 UTF-8(BOM 허용)로 직접 읽습니다. 이 PC에서 검증된 launcher는 `D:/isaacsim/python.bat`입니다.
설정 변경 후 backend를 재시작하세요. JSON 응답은 `charset=utf-8`이고 owned child는 `PYTHONUTF8=1`을 사용합니다.
Windows PowerShell에서 raw 응답을 임의의 ANSI 인코딩으로 다시 디코딩하지 마세요.
누락된 launcher/assets는 HTTP 503의 `CURRENT_PREVIEW_*` code, 변경된 artifact/package는 HTTP 409로 거부합니다.
설정 준비 상태는 GUI 재생 성공을 의미하지 않습니다. [Current Preview 기록](docs/current-vla-preview.md)의 기존 capture 실패와 fixture gate는 유지합니다.

Windows launcher와 legacy prediction adapter 테스트를 포함합니다. 실제 Isaac GUI 검증은 아래 설정 후 별도로 수행합니다.
검증 결과(2026-09-28): **pytest 136개, E2E 7개 통과**, production build·compileall·pip check 성공입니다.

기존 replay는 Current Preview와 별도 런타임입니다. 외부 `../simulator`는 read-only이며, 현재 웹의 `image_pixel` / `is_robot_executable=false` Dummy 경로를 전송하지 않습니다. 기존 `run_welding_sample.py --send --prediction`의 입력과 학습된 export를 그대로 사용합니다. 물리 로봇 실행은 비활성입니다.

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

현재 Guided VLA artifact용 별도 simulator package/API가 추가되었습니다. `B_PR_03_0001`의 원본 9-point NPZ와 GT↔H5 검증은 통과했지만, native B_PR fixture 정책이 없어 **B_PR_FIXTURE_SUPPORT_REQUIRED**로 실행을 차단합니다. 기존 sample replay와 별개이며 실제 VLA/Isaac을 다시 실행하지 않았습니다. 입력 패키지, 좌표계 근거, 정확한 assets와 다음 gate는 [Guided VLA → simulator offline 보고](docs/guided-vla-simulator.md)에 있습니다.

후속 B_PR geometry 진단에서는 CAD 접촉선과 두 rigid-transform 후보를 확인했습니다. 승인된 offline USD reader로 실제 tool mesh를 읽어 검사한 현재 판정은 **B_PR_TOOL_CLEARANCE_FAIL**입니다. 두 후보 모두 GT pose의 tool/workpiece 및 시작 pose의 table 교차가 확인됐습니다. Registry 변경은 적용되지 않았고 현재 실행 gate는 계속 false입니다. [B_PR fixture audit](docs/bpr-fixture-audit.md)에 이전 변환·접근 후보를, [실제 tool clearance audit](docs/bpr-tool-clearance-audit.md)에 mesh·관통·prediction·robot 진단과 보존 hash를 기록했습니다.

- **Segmentation:** 실제 검출 없이 중앙 띠를 반환합니다. UI의 기본 입력은 manual mask이며, 자동 마스크는 adapter/API 검증용입니다.
- **Parser:** 두 방향을 인식하는 규칙 기반 Dummy입니다. 일반적인 자연어 의미·부정문·자연어 제외 구문·복합 작업은 지원 범위가 아닙니다. region ID 기반 제외/순서는 체크박스 또는 구조화된 API 필드로 지정합니다.
- **Rough Path:** 각 연결 영역에서 실제 foreground 픽셀을 열별로 최대 32개 샘플링합니다. 영역마다 독립 segment를 생성합니다. 오목하거나 가지가 있는 단일 영역 내부의 최적 경로 탐색은 구현하지 않았습니다.
- **VLA:** 각 Rough segment를 독립 보정하고 segment/region ID를 보존합니다. 두 점 이상인 segment를 **48개 이상의 점**으로 재샘플링하고 완만하게 평활화합니다. 단일 점은 그대로 유지합니다. 학습된 모델이 아닙니다.
- **Validation:** 빈 segment/point, NaN/Inf, 이미지 경계, region 대응/순서/중복, component 근접성을 검사합니다. 각 segment 점의 80% 이상이 자기 영역 안 또는 반올림 좌표 주위 2px 사각 근방에 있어야 합니다. 복잡한 형상의 Dummy 경로는 이 검사에서 거부될 수 있습니다. 모든 보간 선분의 마스크 내부 체류, 용접 품질, 로봇 workspace, collision, joint limits는 보장하지 않습니다.
- **Simulator:** 기존 VLA 샘플 replay와 현재 job의 XYZ diagnostic preview를 독립적으로 제공하며 설정·admission을 분리합니다. Canvas 2D 경로 전송과 물리 로봇 실행 endpoint는 없습니다.

실제 모델은 각 Protocol을 구현하고 `Workflow`에 주입합니다. Remote VLA에는 RGB PNG, binary mask PNG, rough trajectory JSON, 원문 언어, structured instruction을 보내도록 adapter를 구현하면 됩니다. OpenAI orchestrator도 이 상태 머신을 그대로 따릅니다.

실제 로봇 연동은 별도의 좌표계·calibration·robot trajectory schema·simulation 검증·사용자 승인 흐름을 먼저 설계해야 합니다. 2D mask는 계속 visual conditioning으로 보존합니다. 자세한 계약은 [architecture.md](docs/architecture.md)에 있습니다.

이 MVP 저장소는 **단일 백엔드 프로세스**용입니다. `--workers`를 늘리지 마세요. 인증 없는 로컬 개발용이므로 기본 bind는 `127.0.0.1`입니다. 백엔드 job/artifact는 재시작 후에도 보존됩니다. 미확정 Canvas 그리기 이력은 새로고침 시 초기화되며, 저장된 Assistant 대화와 그 대화의 현재 job은 복원됩니다. 저장된 job은 ID로 REST 조회할 수 있습니다. 이미지 교체 시 새 job을 만들며 과거 artifact는 자동 삭제하지 않습니다.

## Trajectory3 추가 확인 대화

Native가 `needs_clarification`으로 종료하면 Assistant에 저장된 질문과 방향 quick reply가 표시됩니다. `위에서 아래로`처럼 명시적인 답변은 현재 승인된 F 마스크를 재사용하여 **Trajectory3만 한 번** 새 session에서 실행합니다. 모호한 답변은 재질문하며 모델을 실행하지 않습니다. 대기 중에는 경로 생성과 Guided VLA가 차단됩니다. 이전 지시·질문·답변은 private provenance에 보존합니다. [상태·native 방향 계약·웹 사용 예](docs/trajectory-clarification.md).

실제 native 질문의 세로 방향 선택지는 `방향/시작/어느 끝` 단어가 없어도 해석합니다. 답변을 먼저 claim하고, 경로 검증 성공 또는 새 질문 반환 후에만 consume합니다. 실패하면 기존 pending 질문과 승인 F 마스크를 유지하며 safe reason code를 표시합니다. 재답변은 새 명시적 요청으로만 실행되며 자동 retry는 없습니다.

## Assistant 작업 판단과 Guided VLA 요청

Assistant의 **AI 판단 요약**은 intent router, 현재 승인/경로 상태, 도구 진행 이벤트에서 생성합니다. 요청 이해·선택 작업·현재/다음 단계가 한 카드에서 갱신되며, 선택 이유와 준비 상태는 접어서 표시합니다. 모델 내부 사고 과정이 아니며 원문 prompt, native Markdown, 좌표 배열, tool arguments, secret/path를 전송하지 않습니다. 새 대화·새 요청·다른 job으로 전환하면 이전 요약을 정리합니다.

`VLA로 실제 궤적 생성해줘`, `VLA로 최종 궤적 만들어줘`, `실제 3D 궤적 생성해줘`, `최종 XYZ 경로 만들어줘`, `run Guided VLA`는 명확한 **현재 Guided VLA 3D prediction 생성 요청**입니다. deterministic router가 SDK tool-choice와 동일한 semantic tool admission을 사용합니다. 승인된 F 마스크, 현재 지시와 Trajectory3 guidance, 단일 용접 영역, 원본 무결성, 서버 설정이 모두 필요합니다. 부족한 단계를 자동으로 실행하지 않습니다. 수정 중인 Canvas draft도 먼저 확정해야 합니다.

설명·질문·상태·기존 결과 확인·부정·연기 요청은 VLA 실행이 아닙니다. `Robot Preview 실행해줘`와 Simulator 확인 요청은 Simulator 패널의 별도 action으로 안내하며 VLA를 자동 생성하지 않습니다. `실제 경로 해줘`처럼 모호한 요청은 먼저 작업 종류를 확인합니다. `VLA 생성 후 시뮬레이터까지 보여줘`는 VLA만 실행하고 Preview는 별도 버튼으로 남깁니다. 물리 실행은 계속 비활성화됩니다.

현재 조건의 `VLA_READY` 결과가 있으면 immutable artifact와 입력 연결을 다시 검증해 재사용합니다. 이 state에서 explicit rerun은 현재 state machine 정책상 차단되며, 자동 유료 재호출·retry·upstream reset은 없습니다. Backend 재시작 후 새 요청부터 적용됩니다. 자동 검증은 fake native/HTTP/Runner를 사용하며 실제 모델은 호출하지 않습니다.


Final 3D predictor와 retrieval 계약: [docs/final-trajectory-gpt.md](docs/final-trajectory-gpt.md). `WELD_FINAL_TRAJECTORY_BACKEND=guided_vla|gpt`는 명시적 선택이며 자동 fallback은 없습니다. GPT의 33점과 Guided VLA의 9점을 각각 보존합니다. 누락된 원본 `vlm_project2.fewshot_examples`는 복원하지 않으며, owned adapter를 process-local import bridge로 주입합니다.

`최종 예측해줘`를 포함한 final XYZ 생성 요청은 generic `run_final_trajectory_prediction` 도구를 사용합니다. `가궤적 만들어줘/예측해줘`는 Trajectory3로 유지합니다. GPT 선택 시 버튼은 `GPT 최종 3D 궤적 예측`, predictor source는 `vlm_final_gpt`로 표시됩니다. `WELD_GPT_RETRIEVAL_MODE=segment2_adapter|local|none`를 명시적으로 선택합니다. Segment2 RGB 검색의 TRAIN 후보를 현재 mask/instruction/2D geometry로 rerank하고 TRAIN H5 teaching을 예제로 구성합니다. Local은 bounded histogram/text/category/geometry heuristic이며, None은 reference 없음과 정확도 미검증을 UI에 표시합니다. Query GT는 허용된 start XYZ 외에는 prediction 이후 metric 계산에만 사용합니다.

최종 궤적 요청은 Agent의 `run_final_trajectory_prediction` 하나로 실행합니다. SDK에는 predictor-specific `run_guided_vla`를 제공하지 않으며, backend 선택값을 Tool 진행 표시와 AI 판단 요약에 반영합니다. Selector가 없으면 기본값은 `guided_vla`입니다. GPT 설정은 `WELD_FINAL_TRAJECTORY_BACKEND=gpt`이며 변경 후 backend를 재시작합니다. Native model/prompt/두 stage/interpolation은 유지하고 owned invocation의 SDK retries는 0입니다. 실패는 raw output을 보존하고 자동 재실행하지 않습니다.

## Preview descriptor maintenance

Explicit metadata-only refresh and pre-GUI failure diagnostics are documented in
[docs/preview-descriptor-refresh.md](docs/preview-descriptor-refresh.md). In the
Simulator panel, stop an active preview before choosing **Preview descriptor 관리
→ Preview descriptor 갱신**. No model, native computation or Isaac launch occurs
as part of the refresh.

## Semantic mask editing and multi-region Rough

결과 표시는 승인/검증/로봇 재생과 분리됩니다. **모델 출력 보기 / 이전 결과 보기**에서 raw·rejected·partial·stale 결과를 확인하고, **현재 경로 보기 · Path Preview**는 XYZ가 있으면 Scene/Relative/Source-frame viewer를 자동 선택합니다. Isaac이 준비되지 않아도 웹 투영을 볼 수 있습니다. Robot Preview는 기존 strict gate를 유지합니다. [전체 표시 정책과 DISPLAY BLOCKER AUDIT](docs/universal-result-visibility.md).

Assistant는 SDK의 `choose_welding_action` 선택 후 마스크 편집/보정/재검출과 Rough/최종 예측을 별도 도구로 처리합니다. 명확한 전체 component 삭제는 draft를 생성하며, Canvas에서 사람이 다시 승인해야 합니다. 채팅 전 자동 저장은 승인이 아닙니다. Trajectory3는 여러 영역을 독립 segment로 처리하고 최종 predictor의 single-region 제한은 최종 단계에서만 적용합니다.

`MASK_REFINE`는 내부 Segment2 adapter로 현재 F RGB·편집 binary mask·보정 지시만 전달합니다. 제거 영역 복원/누락/연결/미완료 출력은 적용을 거부하고 raw evidence를 보존합니다. 검증된 결과도 `AI Refined from Manual` 승인 대기 draft이며, 새 Rough/최종/Simulator 입력에는 사람의 재승인이 필요합니다. 재검출 fallback은 없습니다. 상태: `MASK_REFINEMENT_ADAPTER_READY`, `LIVE_MASK_REFINE_SMOKE_PENDING` (실제 API 호출 미검증). [보정 계약과 offline 검증](docs/mask-refinement.md), [semantic routing/다중 영역 계약](docs/semantic-mask-and-rough.md)을 참고하세요.

Multiview Final GPT and the separate simulation-only RB10 demo are documented in [docs/multiview-mask-robot-demo.md](docs/multiview-mask-robot-demo.md). GPT defaults to available F/R/S4 masks; approval remains provenance. Robot preview selects STRICT or labelled DEMO while physical execution stays disabled.

Current absolute Guided 9-point/GPT 33-point results prioritize the original STP Robot Preview, including exact sample H5/OBJ, native transform/orientation/interpolation and IK/FK. Missing cached readiness does not force Demo. [Strict restoration and successful live proof](docs/strict-robot-restore.md).

Robot Preview binds the selected artifact **and stage** to its numeric XYZ before native preparation. Different selected points fail with `CURRENT_PREVIEW_SELECTED_SOURCE_MISMATCH`; previous outputs and saved simulator playback remain viewable but cannot be current Robot sources. The UI shows prediction identity/counts and distinguishes the original viewer from transformed Demo playback. See the current-prediction audit in [docs/strict-robot-restore.md](docs/strict-robot-restore.md). The current B_PR_03_0001 result is a relative partial GPT output, so its successful Demo does not establish Strict sample-scene readiness.

Both STP Robot modes now show the current sample's exact OBJ, native STP table/environment, RB10 and ATU01035 through the shared sample-scene renderer. Demo reads exact H5 only for native scene placement; its robot targets remain an explicitly scaled/translated copy of the selected immutable prediction. Strict keeps the native rigid transform/interpolation/IK. Select Original Prediction → Robot Preview → Live or latest capture → Stop. The current relative GPT Demo and a separate existing absolute Guided Strict both passed one live launch, without model calls. See the full-scene evidence below in [strict-robot-restore.md](docs/strict-robot-restore.md).

The authoritative `simulator_final` renderer now passes clean standalone and current-artifact web Robot Preview. Its native contact registration produces matching py3_12/Isaac preparation, preserving the original successful py3_12 placement. The thin `dataset_final` adapter executes the native scene/robot/path; owned start/middle/end PNGs are available in the web viewer. Root configuration selects dataset_final after PASS; restart the existing backend to apply it. [Numeric comparison, live evidence, configuration and STP rollback](docs/simulator-final-integration.md).

Robot Preview activation uses the backend's `current_preview.robot_configuration` and at least two finite XYZ points in the selected current-job output. Approval, validation, cached preflight readiness and STOPPED status point counts do not gate the button. With no explicit selection, the catalog chooses current Final, Corners, Derived, Rough/Raw, then Guided geometry; empty Final rows and stale/foreign sources are skipped. The exact artifact/stage is submitted: absolute uses native STRICT, relative/raw uses explicitly labelled DEMO through SimulatorFinalClient, with no strict-failure fallback. This binding change is verified offline; new dataset_final DEMO playback has not been live-smoked.

Capture uses ASCII SDK staging and Python Unicode copy with the original camera. An owned Isaac experience excludes two unused broken RTX sensor dependencies without editing the installed app. Earlier [URDF](docs/simulator-final-urdf-compat.md) and [capture](docs/simulator-final-capture-compat.md) reports retain their historical failures; the integration report supersedes their pending verdicts.

The GPT2 thin adapter invokes native --prediction-only with the genuine current metadata/label/nine-RGB snapshot and verified first H5 XYZ, without a query GT/baseline NPZ. Native Rough/Corners/retrieval/interpolation are unchanged; six native prediction arrays match default evaluation exactly (max difference 0). Completed source XYZ/NPZ are preserved, null evaluation metrics are displayed honestly, and dataset_final STRICT uses an owned diagnostic companion with genuine bound H5 GT while preserving every prediction array. LOCAL TRAIN retrieval now calls the original vlm_embedding_server Python core directly, without SSH, resident daemons or locks. Windows CPU FAISS uses the existing native indexes; approved DINOv2/E5 encoder inference uses CUDA. The B_PR_03_0001 LOCAL smoke and one authorized GPT2 live Final passed (33 finite XYZ, two OpenAI calls, no retrieval rerun/SSH/Isaac). Root .env now selects gpt2; restart the backend to load it. See [current boundary, tests, live evidence and rollback](docs/gpt2-prediction-only.md).
