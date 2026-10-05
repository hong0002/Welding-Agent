import asyncio
import json
from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.agent.config import AgentFault, AgentSettings, public_error
from backend.agent.context import WeldingAgentContext
from backend.agent.service import EVENT_FIELDS
from backend.agent.sessions import SessionStore
from backend.agent.tools import TOOLS
from backend.main import create_app
from tests.agent_fakes import FakeRunner, FakeSimulator, invoke


@pytest.fixture(autouse=True)
def no_openai_network(monkeypatch):
    import openai
    def no_client(*_args, **_kwargs):
        raise AssertionError("Agent tests must inject an offline model, never a real OpenAI client")
    monkeypatch.setattr(openai, "AsyncOpenAI", no_client)
    async def denied(*_args, **_kwargs):
        raise AssertionError("Agent tests must never use a network model")
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)


@pytest.fixture
def agent_app(tmp_path):
    return create_app(tmp_path / "storage", simulator=FakeSimulator(), agent_runner=FakeRunner(),
                      agent_settings=AgentSettings(api_key="sk-unit-private123456", ready_timeout=.1))


def events(response):
    assert response.status_code == 200, response.text
    return [(chunk.splitlines()[0][7:], json.loads(chunk.splitlines()[1][6:]))
            for chunk in response.text.strip().split("\n\n") if chunk.startswith("event:")]


def context(app, job=None, message="왼쪽에서 오른쪽으로 경로 만들어줘"):
    return WeldingAgentContext(job.id if job else None, str(uuid4()), message, app.state.workflow,
                               app.state.simulator, lambda *_: None, ready_timeout=.1)


def masked(app, scene_bytes, mask_bytes):
    workflow = app.state.workflow
    return workflow.set_mask(workflow.upload_scene(scene_bytes).id, mask_bytes)


def test_configuration_file_secret_only(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-inherited-ignored")
    env = tmp_path / ".env"
    missing = AgentSettings.from_env(env)
    assert missing.status()["state"] == "NOT CONFIGURED"
    env.write_text("OPENAI_API_KEY=sk-test-private123\nOPENAI_MODEL=gpt-5.6\nWELD_AGENT_MAX_TURNS=3\n", encoding="utf8")
    settings = AgentSettings.from_env(env)
    assert settings.api_key == "sk-test-private123" and settings.max_turns == 3
    assert settings.status()["state"] == "READY"
    assert settings.api_key not in str(settings.status()) + repr(settings)
    assert replace(settings, enabled=False).status()["state"] == "DISABLED"


@pytest.mark.parametrize('effort,expected',[('low','low'),('light','low'),('high','high'),('invalid','low')])
def test_luna_reasoning_configuration(tmp_path,monkeypatch,effort,expected):
    monkeypatch.delenv('OPENAI_MODEL',raising=False)
    monkeypatch.delenv('WELD_AGENT_REASONING_EFFORT',raising=False)
    env=tmp_path/'agent.env'
    env.write_text(f'OPENAI_MODEL=gpt-6-luna\nWELD_AGENT_REASONING_EFFORT={effort}\n',encoding='utf-8')
    settings=AgentSettings.from_env(env)
    assert settings.model=='gpt-6-luna' and settings.reasoning_effort==expected
    monkeypatch.setenv('WELD_AGENT_REASONING_EFFORT','medium')
    assert AgentSettings.from_env(env).reasoning_effort=='medium'


def test_status_missing_key_and_origin(agent_app):
    service = agent_app.state.agent
    service.settings = AgentSettings(api_key="")
    with TestClient(agent_app) as client:
        assert client.get("/api/agent/status").json()["state"] == "NOT CONFIGURED"
        sid = client.post("/api/agent/sessions").json()["session_id"]
        assert client.post("/api/agent/chat/stream", json={"session_id": sid, "message": "hello"}).status_code == 503
        assert client.post("/api/agent/sessions", headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.post("/api/agent/chat/stream", json={"session_id": sid, "message": "hello", "command": "shell"}).status_code == 422
    assert service.runner.calls == 0


def test_session_contract_and_default_proxy_origin_5174(agent_app,monkeypatch):
    monkeypatch.delenv('WELD_CORS_ORIGINS',raising=False)
    # Build after clearing the override; no live SDK/model is used.
    app=create_app(workflow=agent_app.state.workflow,simulator=FakeSimulator(),agent_runner=FakeRunner(),
        agent_settings=AgentSettings(api_key='offline-placeholder'))
    with TestClient(app) as client:
        paths=client.get('/openapi.json').json()['paths']
        assert set(paths['/api/agent/sessions'])=={'post'}
        assert client.get('/api/agent/sessions').status_code==405
        origin={'Origin':'http://127.0.0.1:5174'}
        created=client.post('/api/agent/sessions',json={},headers=origin)
        assert created.status_code==201
        sid=created.json()['session_id'];UUID(sid)
        assert client.get(f'/api/agent/sessions/{sid}/history').json()==dict(
            session_id=sid,active_job_id=None,messages=[],running=False)
        assert client.post('/api/agent/sessions',json={'session_id':sid},headers=origin).status_code==422
        assert client.post(f'/api/agent/sessions/{sid}/history').status_code==405
        assert client.get(f'/api/agent/sessions/{uuid4()}/history').status_code==404
        assert client.post(f'/api/agent/sessions/{sid}/reset',json={},headers=origin).status_code==200
        assert client.get(f'/api/agent/sessions/{sid}/reset').status_code==405
        assert client.post('/api/agent/sessions',json={},headers={'Origin':'https://evil.example'}).status_code==403
        assert client.post('/api/agent/sessions?command=anything',json={},headers=origin).status_code==403
    assert app.state.agent.runner.calls==0


def test_agent_explicit_origin_policy_remains_strict(agent_app,monkeypatch):
    monkeypatch.setenv('WELD_CORS_ORIGINS','http://127.0.0.1:5173')
    app=create_app(workflow=agent_app.state.workflow,simulator=FakeSimulator(),agent_runner=FakeRunner(),
        agent_settings=AgentSettings(api_key='offline-placeholder'))
    with TestClient(app) as client:
        response=client.post('/api/agent/sessions',json={},headers={'Origin':'http://127.0.0.1:5174'})
        assert response.status_code==403 and response.json()['code']=='invalid_request'
        assert client.post('/api/agent/sessions',json={},headers={'Origin':'http://127.0.0.1:5173'}).status_code==201
    assert app.state.agent.runner.calls==0


def test_tool_schemas_are_semantic_only():
    from backend.agent.tools import SDK_TOOLS
    assert len(TOOLS) == 13
    assert {'run_guided_vla','run_final_trajectory_prediction'}.issubset({t.name for t in TOOLS})
    assert 'run_guided_vla' not in {t.name for t in SDK_TOOLS}
    assert 'run_final_trajectory_prediction' in {t.name for t in SDK_TOOLS}
    for tool in TOOLS:
        schema = tool.params_json_schema
        assert schema["additionalProperties"] is False
        if tool.name == "set_weld_instruction":
            assert set(schema["properties"]) == {"direction", "start_region", "region_order", "skip_regions"}
            assert set(schema["required"]) == set(schema["properties"])
        elif tool.name=='load_welding_scene':
            assert set(schema['properties'])=={'sample_id'}
        else:
            assert schema["properties"] == {}


def test_tools_plan_reuses_workflow_and_rejects_invalid_ids(agent_app, scene_bytes, mask_bytes):
    job = masked(agent_app, scene_bytes, mask_bytes)
    ctx = context(agent_app, job)
    async def run():
        assert (await invoke(ctx, "create_weld_preview_plan"))["code"] == "workspace_changed"
        state = await invoke(ctx, "get_workspace_state")
        assert state["mask_ready"] and state["regions"][0]["region_id"] == 0
        for selection in ([999], [0, 0], [0]):
            result = await invoke(ctx, "set_weld_instruction", direction="left_to_right", start_region=None,
                                  region_order=None, skip_regions=selection)
            assert result["ok"] is False
        await invoke(ctx, "set_weld_instruction", direction="right_to_left", start_region=None, region_order=None, skip_regions=[])
        result = await invoke(ctx, "create_weld_preview_plan")
        assert result["state"] == "VALIDATED" and result["final_points"] == 48
        assert "points" not in result and result["is_robot_executable"] is False
        assert result == await invoke(ctx, "create_weld_preview_plan")
    asyncio.run(run())
    final = agent_app.state.workflow.get_job(job.id)
    assert final.instruction.parser == "GPT-Agent"
    assert final.final_trajectory.segments[0].points[0].x > final.final_trajectory.segments[0].points[-1].x
    assert agent_app.state.simulator.calls == []


@pytest.mark.parametrize("message,allowed", [
    ("용접할 부분 자동으로 찾아서 왼쪽에서 오른쪽으로 해", True),
    ("용접 영역 찾아서 경로 만들어줘", True),
    ("AI로 용접 영역 선택해", True),
    ("내가 표시한 영역을 왼쪽에서 오른쪽으로 용접해", False),
    ("자동으로 찾은 게 이상해. 내가 다시 표시할게", False),
    ("자동 검출하지 마", False),
    ("automatic detection 방법 설명해줘", False),
])
def test_auto_segmentation_requires_latest_explicit_intent(agent_app, scene_bytes, mask_bytes, message, allowed):
    job = masked(agent_app, scene_bytes, mask_bytes)
    original = job.mask.id
    ctx = context(agent_app, job, message)
    async def run():
        await invoke(ctx, "get_workspace_state")
        result = await invoke(ctx, "auto_segment_weld_region")
        if allowed:
            assert result["mask_source"] == "manual" and result["mask_ready"]
            assert result['reused_existing_mask'] is True
            assert (await invoke(ctx, "auto_segment_weld_region"))["code"] == "segmentation_already_attempted"
        else:
            assert result["code"] == "segmentation_intent_required"
    asyncio.run(run())
    assert agent_app.state.workflow.get_job(job.id).mask.id == original
    assert agent_app.state.simulator.calls == []


def test_current_workspace_overrides_history_and_schema_errors(agent_app, scene_bytes, mask_bytes):
    job = masked(agent_app, scene_bytes, mask_bytes)
    ctx = context(agent_app, job)
    async def run():
        await invoke(ctx, "get_workspace_state")
        agent_app.state.workflow.set_mask(job.id, mask_bytes)
        assert (await invoke(ctx, "set_weld_instruction", direction="left_to_right", start_region=None,
                             region_order=None, skip_regions=[]))["code"] == "workspace_changed"
        result = await invoke(ctx, "set_weld_instruction", direction="diagonal", start_region=None, region_order=None, skip_regions=[])
        assert result["code"] == "tool_validation_error"
    asyncio.run(run())


@pytest.mark.parametrize("message", ["지금 만든 경로 시뮬레이션해", "방금 만든 경로 시뮬레이션해", "simulate this preview"])
def test_current_preview_never_runs_sample(agent_app, message):
    with TestClient(agent_app) as client:
        sid = client.post("/api/agent/sessions").json()["session_id"]
        stream = events(client.post("/api/agent/chat/stream", json={"session_id": sid, "message": message}))
        assert any(name == "warning" and data["code"] == "preview_not_connected" for name, data in stream)
        assert stream[-1][1]["ok"] is True
    assert agent_app.state.simulator.calls == [] and agent_app.state.agent.runner.calls == 0


@pytest.mark.parametrize("message", ["경로 만들어줘", "기존 VLA 샘플 실행하지마", "기존 VLA 샘플 실행 방법 설명해"])
def test_simulator_intent_is_enforced_below_model(agent_app, message):
    ctx = context(agent_app, message=message)
    async def run():
        for name in ("start_simulator", "run_existing_vla_sample", "stop_simulator"):
            assert (await invoke(ctx, name))["ok"] is False
    asyncio.run(run())
    assert agent_app.state.simulator.calls == []


def test_explicit_sample_waits_for_ready_and_deduplicates(agent_app):
    ctx = context(agent_app, message="시뮬레이터 시작하고 기존 VLA 샘플 실행해")
    async def run():
        assert (await invoke(ctx, "run_existing_vla_sample"))["code"] == "simulator_not_ready"
        assert (await invoke(ctx, "start_simulator"))["state"] == "READY"
        assert (await invoke(ctx, "run_existing_vla_sample"))["state"] == "RUNNING_SAMPLE"
        await invoke(ctx, "run_existing_vla_sample")
    asyncio.run(run())
    assert agent_app.state.simulator.calls == ["start", "run"]


def test_sse_and_persistent_sessions(agent_app, scene_bytes, mask_bytes):
    job = masked(agent_app, scene_bytes, mask_bytes)
    with TestClient(agent_app) as client:
        sid = client.post("/api/agent/sessions").json()["session_id"]
        for message in ("왼쪽에서 오른쪽으로 만들어줘", "오른쪽에서 왼쪽으로 바꿔줘"):
            stream = events(client.post("/api/agent/chat/stream", json={"session_id": sid, "job_id": str(job.id), "message": message}))
            assert stream[-1] == ("done", {"ok": True, "session_id": sid, "job_id": str(job.id)})
            assert all(set(data) <= EVENT_FIELDS[name] for name, data in stream)
            assert {"tool_started", "tool_completed", "workspace_updated", "assistant_delta"} <= {name for name, _ in stream}
        assert agent_app.state.agent.runner.memories[1]
        store = SessionStore(agent_app.state.agent.sessions.path)
        assert len(store.history(sid)["messages"]) == 4
        assert client.get(f"/api/agent/sessions/{sid}/history").json()["running"] is False
        assert client.post(f"/api/agent/sessions/{sid}/reset").json()["messages"] == []
        memory = store.sdk_session(sid, job.id)
        assert asyncio.run(memory.get_items()) == []
        memory.close()


def test_concurrent_admission_and_manual_edit_rejection(agent_app, scene_bytes, mask_bytes):
    job = masked(agent_app, scene_bytes, mask_bytes)
    service = agent_app.state.agent
    sid, other = service.sessions.create(), service.sessions.create()
    async def run():
        queue = await service.begin(sid, job.id, "경로 만들어줘")
        for session, job_id in ((sid, None), (other, job.id)):
            with pytest.raises(AgentFault, match="실행 중"):
                await service.begin(session, job_id, "again")
        with pytest.raises(AgentFault):
            with service.manual_mutation(job.id):
                pytest.fail("must not mutate")
        with pytest.raises(AgentFault):
            await service.reset(sid)
        await service.close()
        assert not service.history(sid)["running"]
        names = []
        async for frame in service.stream(queue):
            names.append(frame)
        assert 'event: done' in names[-1]
    asyncio.run(run())


@pytest.mark.parametrize("error_name,code", [("MaxTurnsExceeded", "max_turns"), ("AuthenticationError", "authentication_failed"),
    ("RateLimitError", "rate_limit"), ("APITimeoutError", "network_timeout"), ("NotFoundError", "model_unavailable")])
def test_error_mapping_is_redacted(error_name, code):
    error = type(error_name, (Exception,), {})("sk-secret123456 D:/private/secret")
    fault = public_error(error)
    assert fault.code == code and "sk-" not in fault.message and "private" not in fault.message


def test_tool_failure_cannot_be_reported_as_success(agent_app):
    class FailingRunner:
        async def run(self, ctx, _session, _settings):
            await invoke(ctx, "create_weld_preview_plan")
            return "완료했습니다!"
    agent_app.state.agent.runner = FailingRunner()
    with TestClient(agent_app) as client:
        sid = client.post("/api/agent/sessions").json()["session_id"]
        stream = events(client.post("/api/agent/chat/stream", json={"session_id": sid, "message": "plan"}))
    assert stream[-1][1]["ok"] is False
    assert any(name == "error" for name, _ in stream)
    assert "완료했습니다!" not in str(stream)


def test_secret_and_paths_never_in_status_sse_history(agent_app, caplog, monkeypatch):
    from backend.agent.context import logger
    monkeypatch.setattr(logger, "propagate", True)
    secret = agent_app.state.agent.settings.api_key
    class LeakyRunner:
        async def run(self, ctx, _session, _settings):
            ctx.emit("raw_response_event", {"text": secret})
            ctx.emit("warning", {"message": secret, "raw_payload": secret})
            return f"결과 {secret} D:/private/key.env sk-anothersecret123"
    agent_app.state.agent.runner = LeakyRunner()
    with TestClient(agent_app) as client:
        sid = client.post("/api/agent/sessions").json()["session_id"]
        text = client.get("/api/agent/status").text
        text += client.post("/api/agent/chat/stream", json={"session_id": sid, "message": secret}).text
        text += client.get(f"/api/agent/sessions/{sid}/history").text
        assert secret not in text and "private" not in text and "anothersecret" not in text
        assert "raw_payload" not in text and "raw_response_event" not in text
        assert secret not in caplog.text and "anothersecret" not in caplog.text
        assert "session=" in caplog.text and "success=True" in caplog.text


@pytest.mark.parametrize("max_turns,expected_ok", [(8, True), (1, False)])
def test_actual_sdk_streaming_and_turn_limit_with_offline_model(agent_app, max_turns, expected_ok):
    from agents import Model
    from openai.types.responses import Response, ResponseCompletedEvent, ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
    from backend.agent.welding_agent import SDKRunner

    class OfflineModel(Model):
        def __init__(self):
            self.calls = 0

        async def get_response(self, *args, **kwargs):
            raise AssertionError("Must use Runner.run_streamed")

        async def stream_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs):
            assert model_settings.parallel_tool_calls is False and model_settings.store is False
            assert model_settings.reasoning.effort == 'low'
            assert len(tools) == 16
            assert 'run_guided_vla' not in {tool.name for tool in tools}
            assert 'run_final_trajectory_prediction' in {tool.name for tool in tools}
            self.calls += 1
            output = [ResponseFunctionToolCall(type="function_call", name="get_workspace_state", arguments="{}", call_id="offline-call-1")]
            if self.calls > 1:
                assert any(item.get("type") == "function_call_output" for item in input)
                output = [ResponseOutputMessage(id="msg-test", type="message", status="completed", role="assistant",
                    content=[ResponseOutputText(type="output_text", text="현재 작업은 비어 있습니다.", annotations=[])])]
            response = Response(id=f"resp-{self.calls}", created_at=0, model="offline", object="response", output=output,
                parallel_tool_calls=False, temperature=None, tool_choice="auto", tools=[], top_p=None, status="completed")
            yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=0)

    service = agent_app.state.agent
    service.runner = SDKRunner(model_override=OfflineModel())
    service.settings = replace(service.settings, max_turns=max_turns)
    with TestClient(agent_app) as client:
        sid = client.post("/api/agent/sessions").json()["session_id"]
        stream = events(client.post("/api/agent/chat/stream", json={"session_id": sid, "message": "상태 확인해줘"}))
    assert stream[-1][1]["ok"] is expected_ok, stream
    if expected_ok:
        assert any(name == "tool_completed" and data["success"] for name, data in stream)
    else:
        assert any(name == "error" and data["code"] == "max_turns" for name, data in stream)


def test_timeout_waits_for_owned_synchronous_mutation_before_releasing_lease(agent_app, scene_bytes, mask_bytes):
    import threading
    job = masked(agent_app, scene_bytes, mask_bytes)
    entered, release = threading.Event(), threading.Event()
    class SlowRunner:
        async def run(self, ctx, _session, _settings):
            def mutation():
                entered.set()
                assert release.wait(3)
                return "finished"
            return await ctx.work(mutation)
    service = agent_app.state.agent
    service.runner = SlowRunner()
    service.settings = replace(service.settings, run_timeout=.05)
    sid = service.sessions.create()
    async def run():
        queue = await service.begin(sid, job.id, "경로 만들어줘")
        assert await asyncio.to_thread(entered.wait, 2)
        await asyncio.sleep(.12)
        assert service.history(sid)["running"]
        with pytest.raises(AgentFault):
            with service.manual_mutation(job.id):
                pytest.fail("mutation still owns lease")
        release.set()
        await service.close()
        output = [chunk async for chunk in service.stream(queue)]
        assert any('"code": "network_timeout"' in chunk for chunk in output)
        assert not service.history(sid)["running"]
    asyncio.run(run())


def test_disconnected_stream_does_not_cancel_or_replay_run(agent_app):
    class SlowRunner:
        def __init__(self):
            self.calls = 0
        async def run(self, ctx, _session, _settings):
            self.calls += 1
            ctx.emit("tool_started", {"tool": "get_workspace_state", "label": "작업 상태 확인", "call_id": "1"})
            await asyncio.sleep(.08)
            return "완료"
    service = agent_app.state.agent
    service.runner = SlowRunner()
    sid = service.sessions.create()
    async def run():
        queue = await service.begin(sid, None, "상태 확인")
        stream = service.stream(queue)
        assert "decision_summary" in await anext(stream)
        assert "tool_started" in await anext(stream)
        await stream.aclose()
        assert service.history(sid)["running"]
        with pytest.raises(AgentFault):
            await service.begin(sid, None, "상태 확인")
        await service.close()
        assert service.history(sid)["messages"][-1]["text"] == "완료"
        assert service.runner.calls == 1
    asyncio.run(run())


def test_parallel_model_sample_calls_cannot_replay_twice(agent_app):
    ctx = context(agent_app, message="기존 VLA 샘플 실행해")
    agent_app.state.simulator.state = "READY"
    async def run():
        results = await asyncio.gather(invoke(ctx, "run_existing_vla_sample"), invoke(ctx, "run_existing_vla_sample"))
        assert all(result["state"] == "RUNNING_SAMPLE" for result in results)
    asyncio.run(run())
    assert agent_app.state.simulator.calls == ["run"]


def test_job_scoped_sdk_memory_does_not_inherit_old_region_ids(agent_app):
    store = agent_app.state.agent.sessions
    sid = store.create()
    first, second = store.sdk_session(sid, uuid4()), store.sdk_session(sid, uuid4())
    async def run():
        await first.add_items([{"role": "assistant", "content": "Region 123 selected"}])
        assert await second.get_items() == []
    try:
        asyncio.run(run())
    finally:
        first.close(); second.close()


def test_simulator_failure_has_domain_specific_safe_message(agent_app):
    from backend.orchestrator.state_machine import WorkflowError
    def failed_start():
        raise WorkflowError("Isaac launch failed at D:/private/secret", 503)
    agent_app.state.simulator.start = failed_start
    ctx = context(agent_app, message="시뮬레이터 켜줘")
    result = asyncio.run(invoke(ctx, "start_simulator"))
    assert result["ok"] is False and result["code"] == "simulator_error"
    assert "Simulator 탭" in result["message"] and "private" not in result["message"]
