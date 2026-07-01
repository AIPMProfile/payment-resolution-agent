from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional


class ChatRequest(BaseModel):
    user_id: str
    message: str
    ticket_id: Optional[str] = None


class ResponseCard(BaseModel):
    category: str
    reference: str
    response: str
    next_step: str


class ChatResponse(BaseModel):
    ticket_id: str
    ticket_status: str
    card: Optional[ResponseCard] = None
    escalated: bool = False
    message: Optional[str] = None
    feedback_prompt: bool = True


class FeedbackRequest(BaseModel):
    ticket_id: str
    span_id: Optional[str] = None
    helpful_score: int = Field(..., ge=1, le=3)
    failure_reason: Optional[str] = None
    free_text: Optional[str] = None


class FeedbackResponse(BaseModel):
    success: bool


class Stage2Response(BaseModel):
    ticket_id: str
    answer: str  # "yes" | "no"


class Stage2TimelineResponse(BaseModel):
    ticket_id: str
    answer: str  # "yes_as_expected" | "roughly" | "no_took_longer"


class AdminSuggestion(BaseModel):
    id: str
    failure_pattern: str
    affected_layer: str
    affected_category: Optional[str]
    suggested_fix_text: str
    confidence: float
    source_trace_ids: list[str]
    status: str
    created_at: str
    diff: Optional[str] = None


class AnnotateRequest(BaseModel):
    ticket_id: str
    label: str
    note: Optional[str] = None


class ApproveRequest(BaseModel):
    reviewer: str


class RejectRequest(BaseModel):
    reviewer: str
    reason: str


class MetricsResponse(BaseModel):
    policy_pass_rate: float
    helpful_score_distribution: dict
    timeline_accuracy_rate: float
    escalation_rate: float
    cron_failure_counts: dict = Field(default_factory=dict)
    period: str
