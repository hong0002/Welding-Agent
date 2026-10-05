"""Explicit final predictor selection; the Agent never supplies XYZ or backend paths."""
import os
from typing import Protocol
from backend.services.environment import backend_env_values
from backend.model_clients.guided_workflow import WorkflowGuidedVLAClient
from backend.model_clients.guided_vla import GuidedVLAError


class FinalTrajectoryPredictor(Protocol):
    def status(self) -> dict: ...
    def validate_inputs(self, storage, job): ...
    def run(self, storage, job): ...
    def verify_current(self, storage, job): ...
    def check_server(self): ...


def configured_final_predictor(env_file=None):
    values = backend_env_values(env_file)
    backend = os.getenv('WELD_FINAL_TRAJECTORY_BACKEND') or values.get('WELD_FINAL_TRAJECTORY_BACKEND') or 'guided_vla'
    if backend == 'guided_vla':
        return WorkflowGuidedVLAClient()
    if backend == 'gpt':
        from backend.model_clients.gpt_trajectory import GPTTrajectoryPredictor
        return GPTTrajectoryPredictor()
    if backend == 'gpt2':
        from backend.model_clients.gpt2_trajectory import GPT2TrajectoryPredictor, GPT2TrajectorySettings
        return GPT2TrajectoryPredictor(GPT2TrajectorySettings.from_env(env_file))
    # Never silently use another model/backend when configuration is misspelled.
    raise GuidedVLAError('FINAL_TRAJECTORY_BACKEND_INVALID')
