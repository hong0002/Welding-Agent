from typing import Protocol


class IsaacClient(Protocol):
    """Future simulation status integration; preview coordinates cannot be submitted."""

    def status(self) -> dict[str, str | bool]: ...


class DisabledIsaacClient:
    def status(self) -> dict[str, str | bool]:
        return {"enabled": False, "message": "Web preview submission to Isaac is disabled. Existing-sample launcher uses /api/simulator separately."}
