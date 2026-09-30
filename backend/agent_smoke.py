"""Explicit human-invoked LIVE OpenAI check. Never collected or invoked by automated tests."""
import argparse
import asyncio
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw

from backend.agent.config import AgentFault, AgentSettings, ROOT_ENV
from backend.agent.service import AgentService
from backend.orchestrator.workflow import Workflow
from backend.services.storage import LocalStorage


class SmokeSimulator:
    def status(self):
        return {"state": "STOPPED", "can_start": False, "can_stop": False, "can_run_sample": False,
                "sample_id": None, "latest_sample": None}

    def start(self):
        raise AgentFault("smoke_only", "Live smoke에서는 Simulator를 실행하지 않습니다.")

    run_sample = stop = start


def png(image):
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


async def smoke(settings, plan):
    root = Path(__file__).resolve().parents[1] / ".cache" / "agent-smoke" / str(uuid4())
    workflow = Workflow(LocalStorage(root))
    job = None
    if plan:
        job = workflow.upload_scene(png(Image.new("RGB", (160, 90), "gray")))
        mask = Image.new("L", (160, 90))
        ImageDraw.Draw(mask).line([(20, 45), (140, 45)], fill=255, width=9)
        job = workflow.set_mask(job.id, png(mask))
    service = AgentService(workflow, SmokeSimulator(), settings=settings)
    sid = service.sessions.create()
    message = "표시된 영역을 왼쪽에서 오른쪽으로 용접 경로 만들어줘" if plan else "현재 작업 상태를 한 문장으로 알려줘"
    queue = await service.begin(sid, job.id if job else None, message)
    try:
        while True:
            event, data = await queue.get()
            if event == "tool_completed":
                print(("OK " if data.get("success") else "FAIL ") + data["label"])
            elif event == "assistant_delta":
                print(data["text"])
            elif event == "done":
                return 0 if data["ok"] else 1
    finally:
        await service.close()


def main():
    parser = argparse.ArgumentParser(description="Manually invoke one live OpenAI Agents SDK run (API charges apply).")
    parser.add_argument("--env-file", type=Path, default=ROOT_ENV)
    parser.add_argument("--plan", action="store_true", help="Use a synthetic mask to check the preview tool pipeline.")
    args = parser.parse_args()
    if args.env_file.resolve() != ROOT_ENV.resolve():
        parser.error("Use the project's root .env only.")
    settings = AgentSettings.from_env(args.env_file)
    if settings.status()["state"] != "READY":
        print("Agent 설정이 필요합니다. 프로젝트 .env의 키, 모델, 활성화 설정을 확인하세요.")
        return 2
    return asyncio.run(smoke(settings, args.plan))


if __name__ == "__main__":
    raise SystemExit(main())
