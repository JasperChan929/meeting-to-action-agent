# backend/extractors/schema.py
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class TaskType(str, Enum):
    TODO = "todo"
    EMAIL = "email"
    MEETING = "meeting"
    UNKNOWN = "unknown"


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ActionItem(BaseModel):
    name: str = Field(..., description="任务名称，10字内")
    description: str = Field(..., description="任务详细描述")
    owner: str | None = Field(None, description="负责人，可为空表示待定")
    recipient: str | None = Field(None, description="交付对象，如'设计组'")
    task_type: TaskType
    priority: Priority
    deadline: datetime | None = Field(None, description="截止时间")
    confidence: float = Field(..., ge=0, le=1, description="提取置信度0-1")
    source_text: str = Field(..., description="原文片段")


class ExtractionResult(BaseModel):
    items: list[ActionItem]
    meeting_date: datetime | None = None