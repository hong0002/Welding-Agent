import re
from typing import Protocol

from backend.orchestrator.state_machine import WorkflowError
from backend.schemas import StructuredInstruction


class InstructionParser(Protocol):
    """Language interpretation only. Must not produce trajectory coordinates."""

    def parse(self, text: str) -> StructuredInstruction: ...


class DummyInstructionParser:
    def parse(self, text: str) -> StructuredInstruction:
        compact = re.sub(r"\s+", "", text.lower())
        if any(token in compact for token in ("제외", "빼고", "건너", "skip", "except", "피해서")):
            raise WorkflowError("Use region_selection.skip_regions (region IDs) or the region checkboxes to skip regions.")
        from backend.orchestrator.clarification import answer_direction
        direction = answer_direction(text)
        if direction is None:
            raise WorkflowError(
                "Specify one direction: 왼쪽→오른쪽 / 오른쪽→왼쪽 / 위→아래 / 아래→위."
            )
        return StructuredInstruction(
            direction=direction,
        )
