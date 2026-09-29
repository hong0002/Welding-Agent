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
        left_to_right = bool(re.search(r"왼쪽(?:에서|부터)오른쪽|left(?:to|[-→])right", compact))
        right_to_left = bool(re.search(r"오른쪽(?:에서|부터)왼쪽|right(?:to|[-→])left", compact))
        if left_to_right == right_to_left:
            raise WorkflowError(
                "Specify one supported direction: 왼쪽에서 오른쪽으로 용접해 / 오른쪽에서 왼쪽으로 용접해."
            )
        return StructuredInstruction(
            direction="left_to_right" if left_to_right else "right_to_left",
        )
