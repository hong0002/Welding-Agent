from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ModelFault(Exception):
    MESSAGES = {
        "MODEL_NOT_CONFIGURED": "모델 실행 환경과 참조 입력 설정이 필요합니다.",
        "MODEL_NOT_READY": "모델 환경 또는 인증을 확인하세요. 자동 재시도하지 않았습니다.",
        "MODEL_TIMEOUT": "모델 응답 제한 시간을 초과했습니다. 완료되지 않은 결과는 적용하지 않았습니다.",
        "MODEL_OOM": "모델 메모리가 부족합니다. 자동 재시도하지 않았습니다.",
        "MODEL_INPUT_INVALID": "모델 입력을 확인하세요. 각 영역을 분기나 고리 없는 하나의 가는 용접선으로 표시해주세요.",
        "MODEL_OUTPUT_INVALID": "모델 출력이 좌표·영역·지시 계약과 일치하지 않아 적용하지 않았습니다.",
        "MODEL_PROCESS_FAILED": "모델 실행을 완료하지 못했습니다. 모델 환경을 확인하세요.",
    }

    def __init__(self, code: str):
        self.code = code if code in self.MESSAGES else "MODEL_PROCESS_FAILED"
        self.message = self.MESSAGES[self.code]
        self.status = 422 if self.code.endswith(("INPUT_INVALID", "OUTPUT_INVALID")) else 503
        super().__init__(self.message)


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal[1] = 1
    artifact_id: UUID = Field(default_factory=uuid4)
    model_name: str
    model_version: str
    checkpoint: str | None = None  # Hosted checkpoints are not supplied; never an absolute path.
    source_sha256: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float = Field(ge=0)
    reference_mode: Literal["none", "fixed", "dummy"]
    reference_manifest_sha256: str | None = None
    source_scene_id: UUID | None = None
    source_mask_id: UUID | None = None
    source_rough_id: UUID | None = None
    instruction: str = ""
    region_ids: list[int] = Field(default_factory=list)
    input_transform: str | None = None


class ModelArtifact(BaseModel):
    """Versioned envelope; preview coordinates remain separate in schema-v2 segments."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    kind: Literal["scene", "mask", "rough", "final", "validation"]
    coordinate_space: Literal["image_pixel"] = "image_pixel"
    units: Literal["px"] = "px"
    frame: Literal["image_top_left_x_right_y_down"] = "image_top_left_x_right_y_down"
    is_robot_executable: Literal[False] = False
    provenance: Provenance
