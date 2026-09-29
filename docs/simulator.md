# Windows standalone Isaac와 기존 prediction 연결

이번 연결은 외부 simulator의 기존 VLA 샘플을 실행하는 launcher/monitor다. 웹 Dummy 경로는 전달하지 않으며, physical robot과 OpenAI API는 비활성이다. 외부 simulator, `D:/isaacsim`, `D:/연구/sim`의 원본은 수정하지 않는다.

## 1. 실제 Windows launcher 조사

`D:/isaacsim/python.bat`는 다음을 수행한다.

- `setup_ros_env.bat`, `setup_python_env.bat`를 호출한다. 후자는 Isaac의 `site` 폴더를 PYTHONPATH에 추가한다.
- `CARB_APP_PATH`, `ISAAC_PATH`, `EXP_PATH`를 설정한다.
- 기본적으로 `kit/python/kit.exe`를 실행한다. `PYTHONEXE` 환경변수로 다른 실행기를 선택할 수도 있다.
- 인자를 `%*`로 전달하고 실패 시 exit=1을 반환한다.

따라서 Anaconda base나 설치 폴더의 python.exe 경로만 지정하는 것은 같은 환경이 아니다. 이 PC에서는 **`WELD_SIM_LAUNCHER=D:/isaacsim/python.bat`**를 사용한다. 기존 `WELD_SIM_PYTHON`은 launcher 설정이 비었을 때만 사용하는 optional/deprecated fallback이다.

실제 import-only smoke에서 `sys.executable=D:/isaacsim/kit/python/kit.exe`와 `isaacsim.SimulationApp`, NumPy, SciPy, h5py import 성공을 확인했다. **SimulationApp 객체나 GUI는 생성하지 않았다.** 설치본의 Kit/URDF API까지 기존 시뮬레이터와 호환되는지는 별도의 GUI smoke가 확인해야 한다.

## 2. 기존 두 스크립트와 통신

- `run_welding_simulator.py`: `--serve`를 붙여 `run_rb10_trajectory_with_ATU01035.py`를 실행한다. SimulationApp을 열고 계속 큐를 확인한다.
- `run_welding_sample.py`: 인자 없이 실행하면 curses 메뉴다. 기존 메뉴는 이 스크립트를 `--send --sample ID --prediction --prediction-root ...`로 호출한다. 웹도 같은 CLI를 사용한다.
- `welding_command_queue.py`: `pending/`, `active/`, `results/`의 원자적 JSON 파일로 통신한다. HTTP/socket health 인터페이스는 없다.
- 서버는 초기화와 큐 파일 잠금 후 `[READY] Waiting for samples in <queue-dir>`를 출력한다. 정확한 현재 큐의 이 메시지가 READY 조건이다.
- 준비 프로세스 exit=0은 제출 성공일 뿐이다. 서버의 matching result=done과 scene/actual-weld/prepared-trajectory/report 파일을 확인해야 SUCCEEDED다.

외부 scripts의 cwd는 simulator 루트다. 기존 `--queue-dir`, `--output-dir`를 사용해 생성 파일은 Welding-Agent `.cache/simulator/sessions/<UUID>`로 보낸다. `.pyc` 생성은 차단한다. Windows용 `fcntl.flock` 부분 호환 모듈도 이 저장소에서만 주입한다. 원본 scripts를 패치하지 않는다.

## 3. 확인한 metadata 계약

근거는 외부 `welding_prediction.py`의 `prediction_index()`와 `prediction_targets()`다.

- `prediction_index(root)`는 **`root/*/metadata.json`**을 읽고, `episode_id`를 키로 삼는다. 옆의 `trajectory.npz`도 필요하다. metadata가 없으면 현재 pipeline에서 episode를 발견할 수 없다.
- `prediction_targets()`는 다음 네 필드를 검사한다.

```json
{
  "episode_id": "L_PR_03_0001",
  "coordinate_frame": "source_robot_frame_unaligned_with_isaac",
  "source_units": "mm",
  "scale_to_meters": 0.001
}
```

`source_units=mm`는 원본 H5 좌표 단위다. NPZ의 `predicted_path_m`, `ground_truth_path_m`는 이미 미터이며 다시 스케일링하지 않는다. 두 배열은 같은 길이의 finite `(N>=2,3)`이어야 한다. 원본 코드와 동일하게 H5 trajectory의 XYZ를 N점으로 보간하고 0.001을 곱한 값과 NPZ GT를 비교한다. 최대 오차가 **0.05 mm**를 넘으면 거부한다. 추가 source-unit 배열이 있으면 그 배열과도 일치해야 한다.

`split`과 `metrics`는 curses 메뉴의 분류/표시에 쓰이지만 위 noninteractive CLI에서는 필수 필드가 아니다. 이를 추측해서 만들지 않는다.

### Episode mapping

현재 원본 폴더는 `0000_L_PR_03_0001`이다. `0000_`은 export 순번이며 실제 sample ID는 **`L_PR_03_0001`**이다. 원본 sample index는 H5의 파일 stem을 사용한다. adapter는 `ID` 또는 `<숫자>_ID` 폴더를 정확하게 매칭하며, 중복 후보를 거부한다. 이름뿐 아니라 위 GT/H5 수치 검사를 통과해야 한다.

### 정확한 원본 파일

```text
H5:
D:/연구/sim/Datase/other_data/Other/Other/로봇티칭데이터/Lap/PR(Plate-Round)/03(3mm)/L_PR_03_0001/L_PR_03_0001.h5

대응 OBJ:
D:/연구/sim/Datase/other_data/Other/Other/모델링 데이터/Lap/PR(Plate-Round)/03(3mm)/L_PR_03_0001/L_PR_03_0001.obj

Prediction:
D:/연구/sim/welding_validation_all/0000_L_PR_03_0001/trajectory.npz
```

실제 H5 trajectory는 `(150,6)`, prediction/GT는 각각 `(33,3)`이다. GT/H5 최대 오차는 **0.0000977538 mm**였다. 캐시 복사본을 외부 `prediction_index`와 `prediction_targets`에 직접 넣은 계약 검사도 통과했다. 이 검사는 입력 매칭을 확인하며, 예측 정확도·IK·실제 GUI 재생 성공을 의미하지 않는다.

### 과거 solution NPZ는 직접 사용하지 않음

조사한 `rb10_h5_trajectory_solution.npz`, `rb5_h5_trajectory_solution.npz`, `validation_prediction_rb10_solution.npz`에는 현재 서버가 요구하는 `tracking_point=mounted_fixture_v2`가 없다. validation prediction solution에는 필수 `tcp_pose_xyz_mm_rpy_deg`도 없다. 현재 서버는 이를 stale trajectory로 거부한다. 따라서 파일 이름만 보고 재사용하지 않고 기존 `run_welding_sample.py`가 현재 장착 방식에 맞게 다시 준비하도록 한다.

## 4. 정확한 data root와 legacy adapter

원본 `open_samples()`는 `--data-root` 밑에 **`1.데이터/Other`**를 덧붙인다. 추출 H5가 없으면 그 아래 `Other.zip`을 찾는다. 현재 `D:/연구/sim/Datase/other_data/...` 계층은 이 구조가 아니므로 그 어느 중간 폴더도 그대로 `--data-root`로 지정하지 않는다.

기존 CLI의 `--samples-dir`는 추출 폴더를 재귀 탐색한다. 이 PC의 설정은 다음과 같다.

```dotenv
WELD_SIM_SAMPLES_DIR=D:/연구/sim/Datase/other_data/Other/Other/로봇티칭데이터
```

이 폴더는 티칭 H5 트리다. Windows에서는 원본 코드의 `str(Path(member))`가 역슬래시를 사용하여 `/` 기반 OBJ 경로 치환이 적용되지 않는다. 티칭 폴더를 직접 선택하면 기존 fallback이 이름이 `로봇티칭데이터`인 ancestor를 찾고, 형제 `모델링 데이터` 폴더의 OBJ를 정확하게 찾는다. `Other/Other`를 root로 하면 이 fallback도 사용할 수 없어 OBJ를 찾지 못한다. 위 설정으로 실제 대응 OBJ의 존재를 확인했다.

`WELD_SIM_SAMPLES_DIR`가 있으면 `--samples-dir`를 전달하고 `--data-root`는 전달하지 않는다. `WELD_SIM_DATA_ROOT`는 기존 `3.개방데이터/1.데이터/Other` 구조를 사용하는 다른 환경을 위한 설정으로 유지한다.

현재 export에는 metadata가 없으므로 **legacy adapter가 필요**하다. 명시적으로 `WELD_SIM_PREDICTION_FORMAT=legacy_npz`를 선택한다. 기본값 `metadata`에서는 누락을 오류로 안내하며 자동으로 의미를 추정하지 않는다.

`backend/services/legacy_prediction_adapter.py`는 다음을 수행한다.

1. 정확한 episode와 유일한 H5를 찾는다.
2. 원본을 읽기 전용으로 열고 shape, finite values, 단위 배열, 이름 및 GT/H5 대응을 검사한다. 맞지 않는 샘플을 정렬·보정해 통과시키지 않는다.
3. `.cache`의 매 실행 전용 폴더에 NPZ를 **바이트 그대로 복사**한다. 확인한 네 metadata 필드만 생성한다.
4. 원본 H5/NPZ 경로와 SHA-256, 검사 오차를 `import_report.json`에 기록한다. 기존 metadata와 충돌하면 거부한다.
5. 임시 export root를 기존 sample CLI의 `--prediction-root`에 전달한다. H5와 OBJ는 원래 위치에서 읽는다.

adapter는 sample과 같은 소유 프로세스 트리 안에서 실행되므로 타임아웃과 Stop으로 취소된다. 재실행마다 다른 prediction cache를 사용한다. 원본 NPZ, H5, metadata 및 과거 solution은 변경하지 않는다. 별도 모델 추론이나 GT 대체도 하지 않는다.

## 5. 이 PC의 .env

프로젝트 루트 `.env`에 실제 확인한 값으로 작성했다. `.env`는 Git에서 제외되며, 보편적인 항목 설명은 `.env.example`에 있다.

```dotenv
WELD_SIM_ROOT=D:/Research_and_Paper/2026경남AISW경진대회/code/simulator
WELD_SIM_LAUNCHER=D:/isaacsim/python.bat
WELD_SIM_SAMPLE_ID=L_PR_03_0001
WELD_SIM_SAMPLES_DIR=D:/연구/sim/Datase/other_data/Other/Other/로봇티칭데이터
WELD_SIM_PREDICTION_ROOT=D:/연구/sim/welding_validation_all
WELD_SIM_PREDICTION_FORMAT=legacy_npz
WELD_SIM_STARTUP_TIMEOUT=180
WELD_SIM_SAMPLE_TIMEOUT=300
WELD_SIM_DURATION=15
```

`WELD_SIM_PYTHON`와 `WELD_SIM_DATA_ROOT`는 이 PC 설정에서 생략한다. 프런트엔드는 이 값이나 명령을 변경할 수 없다. 필요하면 timeout을 늘릴 수 있으며 모든 시간값은 `(0,3600]`초여야 한다. 설정 변경 후 backend를 재시작한다.

## 6. Launcher와 process lifecycle

`SimulatorClient`/`LocalSimulatorClient`는 Preview Workflow와 별도로 주입한다. Preview는 EMPTY → … → VALIDATED 그대로이며 validation은 simulator를 자동 실행하지 않는다.

- 외부 실행 script allowlist는 `run_welding_simulator.py`, `run_welding_sample.py`뿐이다. 브라우저 action body는 빈 `{}`만 허용한다.
- 가벼운 backend-Python bootstrap을 시작하고 Windows kill-on-close Job Object에 먼저 할당한다. 이후 gate를 열어 배치 또는 executable을 실행한다. backend Python은 **gate만 담당**하며 실제 simulator는 설정한 Isaac launcher로 실행한다.
- 배치는 고정된 `%SystemRoot%/System32/cmd.exe /D /V:OFF /S /C`로 실행하며 `shell=False`를 유지한다. COMSPEC이나 브라우저 입력으로 실행기를 선택하지 않는다.
- cmd 명령줄에는 관리자가 설정한 launcher와 고정된 runner만 넣는다. Unicode/공백/괄호는 지원한다. 이 두 경로의 `% ! ^ & | < > "` 및 줄바꿈은 이중 CALL 확장 위험 때문에 거부한다.
- 샘플/데이터/출력 경로는 JSON 환경변수로 전달하고, runner 안에서 Python argv로 설정한다. 이 값은 cmd 해석을 거치지 않는다. `PYTHONEXE`는 제거해 Anaconda 등의 우발적 override를 방지한다.
- 외부 script 실행과 별도로 고정된 내부 import probe mode만 제공한다. 이는 SimulationApp을 생성하지 않는다.
- runtime lease로 backend 사이의 중복 소유를 막고, 새 session queue로 오래된 요청 재실행을 막는다. 수동으로 실행된 다른 프로세스에는 붙거나 종료하지 않는다.
- stdout/stderr는 최근 200줄을 보관한다. readiness/sample timeout, 실패, Stop, backend 정상 종료와 Windows backend process exit 시 소유 트리를 정리한다. 강제 Stop은 저장 작업을 중단할 수 있다.

상태는 STOPPED → STARTING → READY → RUNNING_SAMPLE → READY이며 실패 시 FAILED다. 시작 신호 이후에는 프로세스 생존을 감시한다. 주기적인 responsiveness heartbeat는 아니며 멈춘 재생은 sample timeout으로 감지한다. 정상 완료는 exit=0 + matching result=done + 기대 artifact/report를 모두 요구한다.

## 7. API와 명시적 import 검사

| Endpoint | 동작 |
|---|---|
| GET `/api/simulator/status` | 상태, PID, 설정 오류, latest sample, configuration_diagnostics |
| GET `/api/simulator/logs` | 최근 stdout/stderr/bridge 로그 |
| POST `/api/simulator/start` | `{}`만 허용, 202 STARTING |
| POST `/api/simulator/run-sample` | READY에서만 기존 prediction 실행, 202 |
| POST `/api/simulator/stop` | 소유한 실행 취소/종료, 반복 호출 가능 |

status의 `configuration_diagnostics`는 `isaac_launcher_configured`, `isaac_launcher`, `launcher_kind`, `isaac_import_check`, `prediction_format`, `samples_dir` 등을 포함한다. status 조회는 import나 프로세스 실행을 하지 않는다.

명시적 진단은 다음 명령이다. import만 수행하고 GUI를 생성하지 않으며 45초 제한이 있다. 결과는 `.cache/simulator/import-check.json`에 저장한다. status는 마지막 결과와 확인 시각을 보여준다. launcher 경로나 수정시각이 바뀌면 not_run으로 표시한다. 환경/의존성 변경 후에는 다시 실행해야 한다.

```powershell
.\.venv\Scripts\python.exe -m backend.simulator_smoke --env-file .env
```

## 8. 사람이 실행할 최종 GUI smoke

터미널 1, 프로젝트 루트에서:

```powershell
cd 'D:\Research_and_Paper\2026경남AISW경진대회\code\Welding-Agent'
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m backend.simulator_smoke --env-file .env
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --env-file .env --host 127.0.0.1 --port 8000
```

기존 backend가 8000을 사용 중이면 해당 backend를 정상 종료한 뒤 재시작한다. 실제 GUI 실행 중에는 `--reload`를 생략한다. reload/종료는 소유한 simulator도 종료한다. 단일 worker와 loopback을 사용한다.

터미널 2:

```powershell
cd 'D:\Research_and_Paper\2026경남AISW경진대회\code\Welding-Agent\frontend'
npm.cmd run dev
```

브라우저 `http://127.0.0.1:5173`의 Simulator 패널에서 **Start Simulator → READY → Run Existing Welding Sample → SUCCEEDED → Stop Simulator**를 실행한다. 사용자가 버튼을 누를 때만 GUI가 열린다. Run 로그의 `[LEGACY_PREDICTION]`, `[QUEUED]`와 최종 결과를 확인한다.

동일 작업을 명시적으로 실행하는 PowerShell API 명령:

```powershell
$simApi = 'http://127.0.0.1:8000/api/simulator'
Invoke-RestMethod "$simApi/status" | ConvertTo-Json -Depth 8
Invoke-RestMethod "$simApi/start" -Method Post -ContentType 'application/json' -Body '{}'
# status를 다시 조회해 READY가 된 후에만 다음 Run 명령 실행
Invoke-RestMethod "$simApi/status" | ConvertTo-Json -Depth 8
Invoke-RestMethod "$simApi/run-sample" -Method Post -ContentType 'application/json' -Body '{}'
# latest_sample.status가 SUCCEEDED인지 확인; 실패하면 logs 확인
Invoke-RestMethod "$simApi/status" | ConvertTo-Json -Depth 8
Invoke-RestMethod "$simApi/logs" | ConvertTo-Json -Depth 8
Invoke-RestMethod "$simApi/stop" -Method Post -ContentType 'application/json' -Body '{}'
```

이번 작업에서 실제 import와 H5/prediction 계약은 확인했지만 **Isaac GUI의 READY → SUCCEEDED 전체 재생은 자동 실행하지 않았다**. GUI/IK/Kit 버전 오류는 이 수동 smoke에서 확인한다. 재생 실패를 수정하기 위해 외부 scripts나 원본 데이터를 자동 변경하지 않는다.

## 9. 테스트와 이후 연결

pytest는 기존 preview/state 테스트를 유지하며 배치 명령 구성, 실제 가벼운 배치 대역, 한글/공백/괄호와 인자 보존, 환경 진단, metadata 누락, episode 중복/오매칭, GT/H5 불일치, 비유한 값, 단위 불일치, 원본 불변과 cache 제한을 검증한다. 자동 테스트는 실제 Isaac을 실행하지 않는다. 실제 import 검사는 별도로 명시적으로 실행했다.

2026-09-28 검증 결과: **pytest 136개, 브라우저 E2E 7개 통과**, TypeScript/Vite build, compileall, pip check 성공. 실제 batch import-only check 및 실제 NPZ/H5를 이용한 외부 prediction contract 검사도 통과했다. 외부 Python scripts, Isaac batch files, 대상 H5/NPZ의 SHA-256 확인에서 변경은 없었다.

웹 trajectory 연동은 후속 작업이다. 별도 versioned robot trajectory schema, calibrated transforms, 미터/라디안, XYZ와 자세, 타이밍, tool/TCP, IK/joint constraints, segment ID와 용접/이동 구분, 충돌 검증 및 결과/취소 계약이 필요하다. 현재 image_pixel Dummy 경로는 이 인터페이스에 보내지 않는다.
