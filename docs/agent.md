# Welding Assistant

GPT는 자연어 해석·영역 선택·순서·제외·도구 선택을 담당하는 orchestrator입니다. 경로 좌표는 기존 Rough/VLA adapter가 생성하며, 상태 전환과 검증의 최종 권한은 Backend Workflow에 있습니다. 이미지 픽셀 Preview는 실제 로봇 좌표가 아닙니다.

## 실행과 설정

프로젝트 `.venv`의 검증 버전은 `openai-agents==0.22.3`, `openai==3.20.0`입니다. `backend/requirements.txt` 또는 `backend/requirements-lock.txt`를 설치합니다. Isaac Python에는 설치하지 않습니다.

기존 프로젝트 루트 `.env`에 아래 항목을 추가하고 backend를 재시작합니다. 기존 simulator 설정은 보존하세요.

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6
WELD_AGENT_ENABLED=true
WELD_AGENT_MAX_TURNS=8
WELD_AGENT_RUN_TIMEOUT=420
```

키는 **프로젝트 루트 `.env`만** 읽습니다. 프로세스 환경의 `OPENAI_API_KEY`는 사용하지 않습니다. 키 외 설정은 환경변수가 `.env`보다 우선합니다. 모델명은 `AgentSettings`에서 관리하며 기본 `gpt-5.6`을 환경변수로 교체할 수 있습니다. 사용 모델의 접근 권한은 실제 호출 시 확인됩니다. READY는 로컬 설정 완료를 의미하며 네트워크·계정 권한 검증을 뜻하지 않습니다. `GET /api/agent/status`는 OpenAI에 접속하지 않습니다.

키 미설정 또는 `WELD_AGENT_ENABLED=false`이면 채팅은 비활성화되지만 수동 Preview와 Simulator 패널은 계속 동작합니다. 프런트엔드에는 키 존재 여부만 전달하며 `VITE_` 환경변수로 키를 설정하면 안 됩니다.

## 구조와 도구

```text
Assistant → binary mask preflight → POST chat/stream → AgentService
  → Agent / Runner.run_streamed / SQLiteSession
  → function_tool(RunContextWrapper[WeldingAgentContext])
  → existing Workflow / independent SimulatorClient
  → SSE workspace_updated → GET /api/weld/{job_id} → Canvas / stepper
```

`SDKRunner`는 명시적인 `OpenAIResponsesModel`과 `AsyncOpenAI`를 사용합니다. 브라우저는 모델·도구·경로·명령을 추가할 수 없습니다. `create_app(agent_runner=..., agent_settings=...)`로 테스트 어댑터를 주입합니다. 프로덕션에는 fake mode 환경변수나 mock API가 없습니다.

| Tool | 의미 |
|---|---|
| `get_workspace_state()` | 현재 상태, region ID/면적/bounds/centroid/선택 요약 |
| `load_welding_scene(sample_id)` | 이번 메시지의 명시적 sample 불러오기 요청; 9 views만 연결하고 모델 호출 없음 |
| `detect_weld_mask()` | 승인 전에 configured Segment로 실제 마스크 생성; views/counts/승인 요약만 반환 |
| `auto_segment_weld_region()` | 이번 메시지의 명시적 자동 검출 요청만 수행; manual 지시와 redraw 의도는 보호 |
| `set_weld_instruction(direction, start_region, region_order, skip_regions)` | 확정된 마스크의 실제 ID에 대해 구조화 지시 검증·적용 |
| `create_current_weld_plan()` | `Workflow.plan()`으로 설정된 Rough → Dummy VLA → validation 실행 |
| `create_weld_preview_plan()` | 위 도구의 하위 호환 이름 |
| `get_simulator_status()` | 캐시된 Simulator 상태의 허용된 필드만 조회 |
| `start_simulator()` | 이번 사용자 메시지에 명시적 의도가 있을 때 시작, READY까지 대기 |
| `run_existing_vla_sample()` | 설정된 **기존 VLA prediction 샘플**을 한 번 재생 요청 |
| `stop_simulator()` | 이번 사용자 메시지의 명시적 중지 요청에 따라 소유 프로세스 중지 |

GPT 도구에 waypoint, x/y/z 생성, shell, 파일 경로, 로봇 실행 기능은 없습니다. 도구 결과에 전체 point 배열·이미지·로컬 파일 경로를 포함하지 않습니다. 계획 결과는 state, region IDs, rough/final point counts, validation, `coordinate_space=image_pixel`, `is_robot_executable=false`만 반환합니다.

`B_PR_03_0001 불러와`와 명확한 마스크 검출 요청은 shared semantic tool로 직접 routing합니다.
`마스크 씌워줘`, `용접 영역 찾아줘`, `용접할 부분 표시해줘` 등은 planning guard보다 먼저
configured Segment를 실행합니다. Agent/LLM이 pixel/polyline을 그리지 않습니다. 새 AI mask는
승인 대기이며 사람이 F Canvas를 확인/편집하고 **마스크 확정 · F**를 누른 뒤 planning합니다.
기존 mask는 일반 검출 요청에서 유지하며, 명시적 `마스크 다시 찾아줘` / `재검출해줘`만
이전 artifact를 보존하고 새 mask/lineage를 생성합니다. Rough/VLA는 무효화됩니다.
임의 자연어 pixel 편집은 제공하지 않습니다. 수동 Brush/Eraser와 draft 보호는 유지합니다.

수동 Dummy parser와 Agent의 구조화 지시는 `Workflow.apply_instruction()`의 동일한 region 검증·상태 전환을 사용합니다. Agent 경로는 Dummy parser를 거치지 않습니다. unknown/duplicate/empty/inconsistent region 선택은 거부됩니다. 매 턴 현재 workspace를 읽어야 변경할 수 있으며, 읽은 뒤 수정된 마스크/지시는 다시 읽어야 합니다. 동일한 지시와 이미 완료된 계획은 불필요하게 재생성하지 않습니다.

`parallel_tool_calls=False`, 턴 상한(기본 8, 설정 범위 1–20), 요청 전체 기본 420초(`WELD_AGENT_RUN_TIMEOUT`, 30–1200), Agent API 요청 45초·HTTP 자동 재시도 0으로 제한합니다. 도구 호출 자체도 컨텍스트 lock으로 직렬화합니다. Segment/Rough worker는 별도 단계 timeout을 사용하며 [모델 설정](models.md)을 따릅니다. Simulator READY 대기는 최대 185초이며 실제 launcher의 timeout/cleanup 정책은 기존 bridge가 담당합니다.

같은 session **또는** job의 중복 요청은 409입니다. 단일 프로세스의 admission registry와 세션 async lock을 사용하며 Agent 실행 중 해당 job에 대한 기존 수동 mutation API도 409로 거부합니다. 취소/timeout 시 진행 중인 동기 Workflow 작업이 끝나기 전에는 lease를 해제하지 않습니다. SSE 연결이 끊겨도 실행을 다시 시작하거나 자동 재전송하지 않습니다. 진행 중 요청은 서버에서 종료까지 유지되며 브라우저는 history의 running 상태로 결과를 복구합니다. 이 구조는 단일 backend 프로세스용이며 multi-worker 서비스를 지원하지 않습니다.

## Session과 API

`job_id`는 작업, `session_id`는 대화입니다. `<storage>/agent_sessions.db`의 SDK `SQLiteSession`에 모델 대화를 저장합니다. UI용 메시지는 별도 테이블에 정제된 user/assistant 텍스트만 저장합니다. job별 SDK 메모리 네임스페이스를 분리하므로 새 scene이 과거 region ID를 상속하지 않습니다. 같은 job에서 “두 번째 영역 제외” 같은 후속 대화는 유지됩니다. 마스크가 바뀌면 동일 job의 과거 기억보다 현재 workspace가 우선합니다.

| Method | Endpoint | 결과 |
|---|---|---|
| GET | `/api/agent/status` | enabled, api_key_configured, model, sdk_available, state |
| POST | `/api/agent/sessions` | session_id 생성, 빈 body만 허용 |
| GET | `/api/agent/sessions/{session_id}/history` | user/assistant messages, active_job_id, running |
| POST | `/api/agent/chat/stream` | `{session_id, job_id: UUID 또는 null, message}` |
| POST | `/api/agent/sessions/{session_id}/reset` | SDK memory·UI transcript 초기화, 실행 중에는 거부 |

메시지는 공백 제외 1–2000자입니다. Agent mutation은 설정된 CORS origin만 허용합니다. API 오류는 정제된 code/detail을 반환하며 SDK 예외 payload를 전달하지 않습니다. 브라우저 localStorage에는 세션 UUID만 저장합니다. reload하면 대화만 복원하며 캔버스의 저장 전 brush 작업을 복원하는 기능은 없습니다. 새 대화 버튼은 대화 메모리를 지우지만 작업·마스크·경로를 지우지 않습니다.

## Streaming과 UI

SSE event는 `assistant_delta`, `tool_started`, `tool_completed`, `workspace_updated`, `warning`, `error`, `done`만 사용합니다. SDK raw event, hidden reasoning, tool argument JSON은 전달하지 않습니다. 도구 진행은 실행 중 전달하고, 최종 응답 텍스트는 전체를 정제한 후 하나의 `assistant_delta`로 보냅니다. 따라서 텍스트는 토큰별 표시가 아닙니다. Rough/VLA/validation 체크 표시는 실제 `plan()` 성공 후 저장된 결과를 근거로 표시합니다. 도구 실패가 있으면 모델의 성공 주장을 그대로 표시하지 않습니다.

기본 Inspector는 **Assistant | 경로 계획 | 시뮬레이션**입니다. Enter는 전송, Shift+Enter는 줄바꿈이며 한글 IME 조합 중 Enter는 전송하지 않습니다. 전송 즉시 ref latch로 중복 입력을 막고 실행 중 편집·전송을 비활성화합니다.

dirty 마스크가 있으면 기존 full-resolution binary PNG export와 `/api/masks/manual`을 먼저 완료합니다. 확인된 마스크는 다시 업로드하지 않습니다. 빈 마스크를 생성하지 않으며, 확정했던 마스크를 모두 지운 경우 이전 마스크로 계획하지 않고 안내합니다. 표시 opacity는 binary 데이터에 영향을 주지 않습니다. 확정 전 잡음만 남은 마스크는 기존 API의 면적 필터 검증에 따라 실패합니다.

`workspace_updated`는 기존 job endpoint를 재조회해 region, 지시/skip 선택, rough/final segment, validation, stepper를 갱신합니다. Path 탭 클릭이 필요하지 않습니다. 부분 실패 후에도 저장된 workspace를 다시 읽습니다. 경로의 독립 segment 렌더링은 기존 Canvas를 그대로 사용합니다.

**수동 지시 / 디버그**를 펼치면 Dummy parser, 방향 preset, region checkbox, 지시 분석을 사용할 수 있습니다. Path 탭의 Generate/JSON 저장, Simulator의 Start/Run/Stop, Console도 유지합니다.

## Simulator 제한

“지금/방금 만든 경로 시뮬레이션해”는 모델 호출 전에도 검사하여 연결되지 않았음을 알립니다. tool 실행 직전에는 서버가 이번 사용자 메시지의 명시적 의도를 다시 검사합니다. 과거 대화의 동의만으로 실행할 수 없습니다. “기존 VLA 샘플 실행해”, “시뮬레이터 시작하고 기존 샘플 실행해”를 지원합니다. 실행 방법 질문과 부정 표현은 보수적으로 실행을 거부합니다. 이 검사는 일반적인 자연어 이해 모델을 대체하지 않으며 모호한 표현은 명시적인 표현으로 다시 요청해야 합니다.

Planning 완료가 Simulator 시작을 유발하지 않습니다. 웹 preview를 넘기는 parameter 자체가 없습니다. 기존 simulator 설정·외부 prediction·bridge behavior는 유지됩니다. `run_existing_vla_sample` 성공은 **재생 요청 접수**이며 샘플 완료를 의미하지 않습니다. 실제 완료/실패는 Simulator 탭의 기존 결과 검증을 따릅니다.

## Logging / tracing

Agents SDK는 tracing을 지원하고 기본 활성화하지만 여기서는 `set_tracing_disabled(True)` 및 `RunConfig(tracing_disabled=True, trace_include_sensitive_data=False)`로 비활성화합니다. 응답도 `store=False`입니다. 로컬 SQLite 메모리는 별도로 유지됩니다. `welding.agent` 로그에는 session/job/model/tool, 성공 여부, 지연 시간, 가능한 token count만 기록합니다. HTTP/SDK의 상세 payload 로그를 억제합니다. 키와 일반적인 로컬 경로는 user-visible 텍스트와 transcript에서 정제하며 예외 원문은 전송하지 않습니다.

## Offline 검증과 수동 live smoke

자동 테스트는 실제 OpenAI API와 Isaac GUI를 호출하지 않습니다. pytest는 fake runner + SDK offline model을 사용하고, Playwright 전용 factory `tests.agent_e2e_app:create_test_app`는 FakeRunner와 FakeSimulator만 주입합니다. 기존 manual regression도 이 격리된 서버에서 실행합니다. 테스트 storage는 `.cache`의 독립 디렉터리에 저장됩니다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent.py
cd frontend
npm.cmd run test:e2e -- assistant.spec.ts
```

아래 명령만 실제 OpenAI API를 호출합니다. 사람이 `.env`에 자신의 키와 사용 가능한 모델을 설정한 후 프로젝트 루트에서 직접 실행하세요. 자동 테스트에서는 실행하지 않습니다.

```powershell
# 가장 작은 상태 조회: "현재 작업 상태를 한 문장으로 알려줘"
.\.venv\Scripts\python.exe -m backend.agent_smoke --env-file .env
# 독립 synthetic scene/mask로 전체 preview 도구 흐름 확인
.\.venv\Scripts\python.exe -m backend.agent_smoke --env-file .env --plan
```

smoke는 `.cache/agent-smoke/<UUID>`에만 새 작업을 만들며 사용자 작업을 덮어쓰지 않습니다. Simulator는 비활성 어댑터로 고정합니다. 실제 API 비용이 발생하고 모델 접근 권한/네트워크에 따라 실패할 수 있습니다. API 키는 출력하지 않습니다.

공식 참고: [Agents SDK](https://developers.openai.com/api/docs/guides/agents/sdk), [Running agents](https://developers.openai.com/api/docs/guides/agents/running-agents), [모델 안내](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6). 구현은 설치된 SDK 0.22.3의 실제 signature로 검증했습니다.

## 이번 구현의 검증 기록

- 기존 저장분: `Workflow.apply_instruction`, Agent 설정·컨텍스트·프롬프트, 설치된 SDK를 보존하고 이어서 구현했습니다.
- Backend: 전체 pytest 수집에서 기존 두 파일의 `conftest` import 오류를 수정했습니다. 이후 해당 API/multi-region 파일 67개와 미실행 나머지 파일 96개가 통과했습니다. 마지막 Simulator 오류 안내 회귀 1개도 추가로 통과하여 **164개 전체 대상**을 검증했습니다. 전체 명령을 반복 실행하지 않았습니다.
- Frontend: 전체 E2E **21개 통과**. A(자동 mask sync와 Canvas 갱신), B(동일 세션의 두 번째 region 제외), C(현재 preview 실행 차단), D(mock START → READY → 기존 sample 요청) 모두 통과했습니다.
- Production build, Python compileall, pip check 통과. 최초 build의 Vite 임시 파일 권한 오류는 로컬 권한으로 build만 재실행하여 해결했습니다. Vite의 번들 크기 안내는 남아 있습니다.
- 실제 OpenAI API, live smoke, Isaac GUI는 실행하지 않았습니다. CLI의 `--help`만 확인했습니다.

변경 파일 묶음:

- Backend: `backend/agent/{__init__,config,context,prompts,sessions,service,tools,welding_agent}.py`, `backend/agent_routes.py`, `backend/agent_smoke.py`, `backend/main.py`, `backend/orchestrator/workflow.py`.
- Frontend: `frontend/src/{App,api,types,useAssistant,styles}`의 해당 TS/TSX/CSS 파일, `components/AssistantPanel.tsx`, `components/Inspector.tsx`, `components/PathPanel.tsx`.
- Tests: `tests/{__init__,agent_fakes,agent_e2e_app,test_agent}.py`, 기존 `test_api.py`/`test_multi_region.py`의 fixture import, `frontend/e2e/assistant.spec.ts`, 기존 navigation/workflow/workspace spec, `frontend/playwright.config.ts`.
- 설정/문서: `.env.example`, `.gitignore`, `backend/requirements.txt`, `backend/requirements-lock.txt`, `README.md`, `AGENTS.md`, `docs/architecture.md`, 이 문서. 실제 `.env`는 수정하지 않았습니다.

기존 mask/trajectory 알고리즘과 Simulator bridge, 외부 simulator/Isaac 파일은 변경하지 않았습니다.
