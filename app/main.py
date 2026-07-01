from __future__ import annotations
from typing import Optional
"""
FastAPI application entry point.
Mounts frontend static files, registers all routers,
and runs APScheduler (Lifecycle cron jobs) inside the lifespan.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Depends, HTTPException, Header, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import get_settings
from app.db.models import (
    ChatRequest, ChatResponse,
    FeedbackRequest, FeedbackResponse,
    Stage2Response, Stage2TimelineResponse,
    AdminSuggestion, AnnotateRequest, ApproveRequest, RejectRequest, MetricsResponse,
)
from app.lifecycle.chat_handler import handle_chat
from app.lifecycle.followup_cron import run_followup_check, handle_stage2_response, handle_stage2_timeline
from app.lifecycle.autoclose_cron import run_autoclose_check
from app.learning.feedback import submit_feedback
from app.learning.nightly_analysis import run_nightly_analysis
from app.learning.admin_api import (
    get_pending_suggestions, approve_suggestion,
    reject_suggestion, rollback_to_version, get_metrics,
    get_eval_gate_status, annotate_trace,
)
from app.learning.drift_check import run_drift_check
from app.learning.error_discovery import (
    get_traces as discovery_traces,
    get_failure_clusters,
    select_review_samples,
    save_annotation,
    get_convergence,
)
from app.observability.arize_client import setup_tracer, flush_tracer
from app.auth import generate_token, get_current_user

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Rate limiter — keyed by remote IP (10 requests/min per caller on /chat)
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_tracer(s.ARIZE_API_KEY, s.ARIZE_SPACE_ID, s.ARIZE_MODEL_ID)

    # Lifecycle loop scheduled jobs
    scheduler.add_job(run_followup_check, "cron", hour=9, minute=0, id="followup")
    scheduler.add_job(run_autoclose_check, "cron", hour=9, minute=15, id="autoclose")

    # Learning loop nightly analysis
    scheduler.add_job(
        lambda: asyncio.create_task(run_nightly_analysis()),
        "cron", hour=2, minute=0, id="nightly_analysis",
    )

    # Weekly drift detection — every Monday at 03:00
    scheduler.add_job(run_drift_check, "cron", day_of_week="mon", hour=3, minute=0, id="drift_check")

    scheduler.start()
    logger.info("APScheduler started")
    yield
    scheduler.shutdown()
    flush_tracer()  # drain BatchSpanProcessor before process exits


app = FastAPI(title="Payment Resolution Agent", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# --- Auth ---

def _require_admin(authorization: Optional[str] = Header(default=None)) -> None:
    s = get_settings()
    if authorization != f"Bearer {s.ADMIN_API_KEY}":
        raise HTTPException(401, "Unauthorized")


# --- Health check ---

@app.get("/health")
async def health() -> dict:
    from app.db.supabase_client import get_supabase_client
    try:
        get_supabase_client().table("users").select("user_id").limit(1).execute()
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {"status": "ok" if db_status == "ok" else "degraded", "db": db_status}


# --- Auth ---

@app.post("/auth/token")
async def issue_token(body: dict) -> dict:
    """
    Exchange a user_id for a signed session token.
    In production, require OTP or password before issuing — here we verify
    the user_id exists in the DB, which prevents token minting for unknown users.
    """
    user_id = body.get("user_id", "").strip()
    if not user_id:
        raise HTTPException(400, "user_id required")
    from app.db.supabase_client import get_supabase_client
    r = get_supabase_client().table("users").select("user_id").eq("user_id", user_id).execute()
    if not r.data:
        raise HTTPException(404, "User not found")
    return {"token": generate_token(user_id), "user_id": user_id}


# --- Lifecycle: Chat ---

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("10/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    authed_user: Optional[str] = Depends(get_current_user),
) -> ChatResponse:
    # If a valid token is present, override the body's user_id with the verified identity
    if authed_user:
        body = body.model_copy(update={"user_id": authed_user})
    return await handle_chat(body)


# --- Lifecycle: Stage 2: Stage 2 follow-up responses ---

@app.post("/stage2/resolution")
async def stage2_resolution(body: Stage2Response) -> dict:
    return handle_stage2_response(body.ticket_id, body.answer)


@app.post("/stage2/timeline")
async def stage2_timeline(body: Stage2TimelineResponse) -> dict:
    return handle_stage2_timeline(body.ticket_id, body.answer)


# --- Learning: Feedback ---

@app.post("/feedback", response_model=FeedbackResponse)
async def feedback(request: FeedbackRequest) -> FeedbackResponse:
    return await submit_feedback(request)


# --- Learning: Admin ---

@app.get("/admin/suggestions", response_model=list[AdminSuggestion])
async def admin_suggestions(_: None = Depends(_require_admin)) -> list[AdminSuggestion]:
    return await get_pending_suggestions()


@app.post("/admin/suggestions/{suggestion_id}/approve")
async def admin_approve(
    suggestion_id: str,
    body: ApproveRequest,
    _: None = Depends(_require_admin),
) -> dict:
    return await approve_suggestion(suggestion_id, body)


@app.post("/admin/suggestions/{suggestion_id}/reject")
async def admin_reject(
    suggestion_id: str,
    body: RejectRequest,
    _: None = Depends(_require_admin),
) -> dict:
    return await reject_suggestion(suggestion_id, body)


@app.post("/admin/versions/{version_id}/rollback")
async def admin_rollback(
    version_id: str,
    reviewer: str,
    _: None = Depends(_require_admin),
) -> dict:
    return await rollback_to_version(version_id, reviewer)


@app.get("/admin/metrics", response_model=MetricsResponse)
async def admin_metrics(_: None = Depends(_require_admin)) -> MetricsResponse:
    return await get_metrics()


@app.post("/admin/annotate")
async def admin_annotate(
    body: AnnotateRequest,
    _: None = Depends(_require_admin),
) -> dict:
    return await annotate_trace(body.ticket_id, body.label, body.note)


# --- Manual cron triggers (for demo / testing) ---

@app.post("/admin/trigger/followup")
async def trigger_followup(_: None = Depends(_require_admin)) -> dict:
    run_followup_check()
    return {"triggered": "followup"}


@app.post("/admin/trigger/autoclose")
async def trigger_autoclose(_: None = Depends(_require_admin)) -> dict:
    run_autoclose_check()
    return {"triggered": "autoclose"}


@app.post("/admin/trigger/nightly")
async def trigger_nightly(_: None = Depends(_require_admin)) -> dict:
    result = await run_nightly_analysis()
    return result


@app.post("/admin/run-analysis")
async def run_analysis(_: None = Depends(_require_admin)) -> dict:
    result = await run_nightly_analysis(min_cluster_size=1)
    return result


@app.get("/admin/eval-gate")
async def eval_gate(_: None = Depends(_require_admin)) -> dict:
    return await get_eval_gate_status()


@app.post("/admin/trigger/drift-check")
async def trigger_drift_check(_: None = Depends(_require_admin)) -> dict:
    return run_drift_check()


# --- Learning: Error Discovery ---

@app.get("/admin/discovery/traces")
async def discovery_traces_endpoint(
    days: int = Query(default=7), limit: int = Query(default=200),
    _: None = Depends(_require_admin),
) -> list[dict]:
    return discovery_traces(days=days, limit=limit)


@app.get("/admin/discovery/clusters")
async def discovery_clusters(
    days: int = Query(default=7),
    _: None = Depends(_require_admin),
) -> dict:
    return get_failure_clusters(days=days)


@app.get("/admin/discovery/samples")
async def discovery_samples(
    days: int = Query(default=7), count: int = Query(default=20),
    _: None = Depends(_require_admin),
) -> list[dict]:
    return select_review_samples(days=days, count=count)


@app.post("/admin/discovery/annotate")
async def discovery_annotate(
    body: dict,
    _: None = Depends(_require_admin),
) -> dict:
    return save_annotation(
        eval_id=body["eval_id"],
        annotation_text=body["annotation_text"],
        failure_mode=body["failure_mode"],
        reviewer=body.get("reviewer", "admin"),
    )


@app.get("/admin/discovery/convergence")
async def discovery_convergence(
    days: int = Query(default=7),
    _: None = Depends(_require_admin),
) -> dict:
    return get_convergence(days=days)


@app.get("/admin/discovery")
async def discovery_page(
    key: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> FileResponse:
    s = get_settings()
    if key != s.ADMIN_API_KEY and authorization != f"Bearer {s.ADMIN_API_KEY}":
        raise HTTPException(403, "Forbidden")
    return FileResponse("frontend/discovery.html")


# --- User: tickets list + profile ---

@app.get("/user/profile")
async def user_profile(authed_user: Optional[str] = Depends(get_current_user)) -> dict:
    if not authed_user:
        raise HTTPException(401, "Unauthorized")
    from app.db.supabase_client import get_supabase_client
    db = get_supabase_client()
    r = db.table("users").select("user_id, name, phone").eq("user_id", authed_user).execute()
    if not r.data:
        raise HTTPException(404, "User not found")
    return r.data[0]


@app.get("/ticket/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    authed_user: Optional[str] = Depends(get_current_user),
    user_id: Optional[str] = Query(default=None),
):
    uid = authed_user or user_id
    if not uid:
        raise HTTPException(401, "Unauthorized")
    from app.db.supabase_client import get_supabase_client
    db = get_supabase_client()
    r = (
        db.table("tickets")
        .select("ticket_id, status, category, conversation_json, session_id, user_id")
        .eq("ticket_id", ticket_id)
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Ticket not found")
    ticket = r.data[0]
    if ticket["user_id"] != uid:
        raise HTTPException(403, "Forbidden")
    return {
        "ticket_id": ticket["ticket_id"],
        "status": ticket["status"],
        "category": ticket["category"],
        "conversation_json": ticket["conversation_json"],
        "session_id": ticket["session_id"],
    }


@app.get("/user/tickets")
async def user_tickets(authed_user: Optional[str] = Depends(get_current_user)) -> list[dict]:
    if not authed_user:
        raise HTTPException(401, "Unauthorized")
    from app.db.supabase_client import get_supabase_client
    db = get_supabase_client()
    r = (
        db.table("tickets")
        .select("ticket_id, status, category, created_at")
        .eq("user_id", authed_user)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )
    return r.data or []


# --- Frontend static files ---

app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("frontend/index.html")


@app.get("/admin")
async def admin_panel(
    key: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> FileResponse:
    s = get_settings()
    if key != s.ADMIN_API_KEY and authorization != f"Bearer {s.ADMIN_API_KEY}":
        raise HTTPException(403, "Forbidden")
    return FileResponse("frontend/admin.html")
