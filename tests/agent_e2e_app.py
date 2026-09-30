"""Explicit Playwright-only factory. No real model or simulator can be constructed here."""
from backend.agent.config import AgentSettings
from backend.main import create_app
from tests.agent_fakes import FakeRunner, FakeSimulator


def create_test_app():
    return create_app(simulator=FakeSimulator(), agent_runner=FakeRunner(),
                      agent_settings=AgentSettings(api_key="offline-test-placeholder", ready_timeout=1))
