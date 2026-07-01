"""
Classifier tests — mock the Anthropic client so no real API calls are made.
Tests verify the classification logic for valid and invalid responses.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_classifies_upi_failure():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="UPI_FAILURE")]

    with patch("app.core.classifier.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        from app.core.classifier import classify_intent
        result = await classify_intent("My Swiggy payment was debited but not credited")
        assert result == "UPI_FAILURE"


@pytest.mark.asyncio
async def test_classifies_pot_withdrawal():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="POT_WITHDRAWAL")]

    with patch("app.core.classifier.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        from app.core.classifier import classify_intent
        result = await classify_intent("My pot withdrawal is stuck")
        assert result == "POT_WITHDRAWAL"


@pytest.mark.asyncio
async def test_invalid_response_falls_back_to_out_of_scope():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="CARD_DISPUTE")]  # not a valid category

    with patch("app.core.classifier.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        from app.core.classifier import classify_intent
        result = await classify_intent("I want to dispute my card charge")
        assert result == "OUT_OF_SCOPE"


@pytest.mark.asyncio
async def test_classifies_out_of_scope():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="OUT_OF_SCOPE")]

    with patch("app.core.classifier.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        from app.core.classifier import classify_intent
        result = await classify_intent("How do I change my PIN?")
        assert result == "OUT_OF_SCOPE"


@pytest.mark.asyncio
async def test_classifies_unclear():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="UNCLEAR")]

    with patch("app.core.classifier.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        from app.core.classifier import classify_intent
        result = await classify_intent("money stuck")
        assert result == "UNCLEAR"


@pytest.mark.asyncio
async def test_unclear_is_not_out_of_scope_fallback():
    """UNCLEAR must be a recognised category, not fall back to OUT_OF_SCOPE."""
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="UNCLEAR")]

    with patch("app.core.classifier.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        from app.core.classifier import classify_intent
        result = await classify_intent("payment stuc")
        assert result == "UNCLEAR"
        assert result != "OUT_OF_SCOPE"
