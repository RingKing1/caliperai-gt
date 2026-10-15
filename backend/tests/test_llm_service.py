"""Unit tests for LLMService provider selection / disabled-mode fallback."""
import pytest

from app.core.config import settings
from app.services.llm_service import LLMProvider, LLMService


@pytest.mark.parametrize("value", ["none", "NONE", " None ", "", "disabled", "off"])
def test_disabled_provider_falls_back_to_mock(value, monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", value)
    assert LLMService().provider == LLMProvider.MOCK


def test_ollama_provider_is_preserved(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    assert LLMService().provider == LLMProvider.OLLAMA


def test_unknown_provider_still_raises(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "bogus")
    with pytest.raises(ValueError):
        LLMService()
