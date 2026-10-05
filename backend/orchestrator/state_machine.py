from backend.schemas import StateEvent, WeldJob, WorkflowState, utc_now


class WorkflowError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


class StateMachine:
    sequence = [s for s in WorkflowState if s != WorkflowState.VLA_READY]

    @classmethod
    def require(cls, job: WeldJob, *allowed: WorkflowState) -> None:
        if job.state not in allowed:
            expected = ", ".join(state.value for state in allowed)
            raise WorkflowError(
                f"Invalid state {job.state.value}; expected {expected}.", 409
            )

    @classmethod
    def advance(cls, job: WeldJob, target: WorkflowState) -> None:
        if target == WorkflowState.VLA_READY:
            cls.require(job, WorkflowState.ROUGH_PATH_READY)
            if not job.rough3d or not job.vla_prediction:
                raise WorkflowError("Guided VLA completion is required.", 409)
            cls.record(job, target, "guided_vla_completed")
            return
        current_index = cls.sequence.index(job.state)
        if current_index + 1 >= len(cls.sequence) or cls.sequence[current_index + 1] != target:
            raise WorkflowError(f"Cannot transition {job.state.value} → {target.value}.", 409)
        cls.record(job, target, "pipeline_step")

    @classmethod
    def replace_mask(cls, job: WeldJob) -> None:
        cls.require(job, *cls.sequence[1:], WorkflowState.VLA_READY)
        job.instruction = None
        cls.clear_trajectories(job)
        cls.record(job, WorkflowState.MASK_READY, "mask_confirmed; downstream_invalidated")

    @classmethod
    def replace_instruction(cls, job: WeldJob) -> None:
        cls.require(job, *cls.sequence[2:], WorkflowState.VLA_READY)
        cls.clear_trajectories(job)
        cls.record(job, WorkflowState.INSTRUCTION_READY, "instruction_parsed; downstream_invalidated")

    @staticmethod
    def clear_trajectories(job: WeldJob) -> None:
        job.rough_trajectory = None
        job.final_trajectory = None
        job.validation = None
        job.rough3d = None
        job.native_output = None
        job.trajectory_clarification = None
        job.planning_status = 'NOT_READY'
        job.vla_prediction = None
        job.raw_final_prediction = None

    @staticmethod
    def record(job: WeldJob, target: WorkflowState, reason: str) -> None:
        job.state = target
        job.updated_at = utc_now()
        job.history.append(StateEvent(state=target, reason=reason))
