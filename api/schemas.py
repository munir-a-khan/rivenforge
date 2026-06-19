from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

WeaponTypeStr = Literal["primary", "secondary", "melee", "archgun", "robotic", "stat sticks"]
CropModeStr = Literal["new_card", "single_card", "full"]
CapturePathStr = Literal["mss", "dxgi", "mss(dark)"]


class HealthResponse(BaseModel):
    ready: bool = True
    capture_path: CapturePathStr = "mss"


class SaveResponse(BaseModel):
    saved: bool


class RollStartRequest(BaseModel):
    weapon: str
    weapon_type: WeaponTypeStr
    profiles: list[dict[str, Any]] = Field(default_factory=list)
    roll_limit: int = 100
    rag_threshold: float = 0.6
    animation_wait: float = 2.5


class RollStartResponse(BaseModel):
    session_id: str


class RollStopResponse(BaseModel):
    stopped: bool


class RagStatusResponse(BaseModel):
    ready: bool
    entries: int


class RagRebuildResponse(BaseModel):
    job_id: str


class AnalyzeResponse(BaseModel):
    parse: dict[str, Any]
    decision: dict[str, Any]
    confidence: float
    capture_path: CapturePathStr = "mss"
    brightness: int = 0
    brightness_p95: int = 0
    raw_image_size: tuple[int, int] | None = None
    crop_image_size: tuple[int, int] | None = None
    review_reasons: list[str] = Field(default_factory=list)


class CaptureStatusResponse(BaseModel):
    available: bool
    found: bool
    visible: bool
    minimized: bool
    foreground: bool
    rect: tuple[int, int, int, int] | None = None
    capture_backends: dict[str, bool] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
