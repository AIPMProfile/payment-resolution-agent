"""
OpenTelemetry tracer configured for Arize AX via arize-otel register().
Degrades gracefully: if ARIZE_API_KEY is empty, a no-op tracer is used and
no exception is raised. The agent continues to function normally.
"""
from __future__ import annotations

import logging
from opentelemetry import trace

logger = logging.getLogger(__name__)

_tracer: trace.Tracer | None = None
_provider = None  # retained so lifespan can force-flush on shutdown


def setup_tracer(arize_api_key: str, arize_space_id: str, model_id: str) -> None:
    global _tracer, _provider

    if arize_api_key and arize_space_id:
        try:
            from arize.otel import register
            from openinference.instrumentation.anthropic import AnthropicInstrumentor

            _provider = register(
                space_id=arize_space_id,
                api_key=arize_api_key,
                project_name=model_id,
            )
            AnthropicInstrumentor().instrument(tracer_provider=_provider)
            logger.info("Arize OTLP tracer configured: %s", model_id)
        except Exception as exc:
            logger.warning("Arize tracer setup failed, dropping traces: %s", exc)

    _tracer = trace.get_tracer(model_id)


def flush_tracer(timeout_ms: int = 5000) -> None:
    """Force-flush the BatchSpanProcessor before process exit."""
    if _provider is not None:
        try:
            _provider.force_flush(timeout_millis=timeout_ms)
            _provider.shutdown()
            logger.info("Arize tracer flushed and shut down")
        except Exception as exc:
            logger.warning("Arize tracer flush failed: %s", exc)


def get_tracer() -> trace.Tracer:
    if _tracer is None:
        return trace.get_tracer("noop-tracer")
    return _tracer


def span_attrs(user_id: str, ticket_id: str, model_id: str = "", **extra) -> dict:
    """Build standard span attributes for every child span."""
    attrs = {"user.id": user_id, "ticket.id": ticket_id}
    if model_id:
        attrs["model.id"] = model_id
    attrs.update({str(k): str(v) for k, v in extra.items()})
    return attrs
