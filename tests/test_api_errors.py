"""
End-to-end API error handling tests.
These test the actual HTTP layer, not mocked handlers.
Catches the class of bug where the frontend receives a non-200 response
and the error path is not handled.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_chat_without_token_still_works(client):
    with patch("app.lifecycle.chat_handler.handle_chat") as mock_chat:
        mock_chat.return_value = MagicMock(
            ticket_id="t1", ticket_status="open",
            card=MagicMock(category="UPI_FAILURE", reference="TXN001", response="test", next_step="wait"),
            escalated=False, message=None, feedback_prompt=True,
        )
        mock_chat.return_value.model_dump = lambda: {
            "ticket_id": "t1", "ticket_status": "open",
            "card": {"category": "UPI_FAILURE", "reference": "TXN001", "response": "test", "next_step": "wait"},
            "escalated": False, "message": None, "feedback_prompt": True,
        }
        res = client.post("/chat", json={"user_id": "USR001", "message": "test"})
        assert res.status_code == 200
        data = res.json()
        assert "ticket_id" in data


def test_chat_with_invalid_token_returns_401(client):
    res = client.post(
        "/chat",
        json={"user_id": "USR001", "message": "test"},
        headers={"X-Auth-Token": "garbage-token"},
    )
    assert res.status_code == 401


def test_chat_with_expired_token_returns_401(client):
    from app.auth import _sign
    from app.config import get_settings
    import base64
    expired_payload = base64.urlsafe_b64encode(b"USR001:1000000000").decode()
    sig = _sign(expired_payload, get_settings().AUTH_SECRET_KEY)
    expired_token = f"{expired_payload}.{sig}"

    res = client.post(
        "/chat",
        json={"user_id": "USR001", "message": "test"},
        headers={"X-Auth-Token": expired_token},
    )
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()


def test_auth_token_for_unknown_user_returns_404(client):
    with patch("app.db.supabase_client.get_supabase_client") as mock_db:
        mock_result = MagicMock()
        mock_result.data = []
        mock_db.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result
        res = client.post("/auth/token", json={"user_id": "FAKE_USER"})
        assert res.status_code == 404


def test_auth_token_empty_user_returns_400(client):
    res = client.post("/auth/token", json={"user_id": ""})
    assert res.status_code == 400


def test_chat_missing_message_returns_422(client):
    res = client.post("/chat", json={"user_id": "USR001"})
    assert res.status_code == 422


def test_feedback_invalid_score_returns_422(client):
    res = client.post("/feedback", json={
        "ticket_id": "t1",
        "helpful_score": 5,
    })
    assert res.status_code == 422


def test_admin_without_auth_returns_401(client):
    res = client.get("/admin/suggestions")
    assert res.status_code == 401


def test_admin_with_wrong_key_returns_401(client):
    res = client.get("/admin/suggestions", headers={"Authorization": "Bearer wrong-key"})
    assert res.status_code == 401


def test_health_returns_200(client):
    with patch("app.db.supabase_client.get_supabase_client") as mock_db:
        mock_result = MagicMock()
        mock_result.data = [{"user_id": "USR001"}]
        mock_db.return_value.table.return_value.select.return_value.limit.return_value.execute.return_value = mock_result
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] in ("ok", "degraded")
