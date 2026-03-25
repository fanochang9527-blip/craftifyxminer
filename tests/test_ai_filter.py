"""Unit tests for pipeline.ai_filter — Level 3 LLM Bio 过滤."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.ai_filter import AIFilter, LLMClient, SYSTEM_PROMPT


class TestLLMClient:
    def test_init_sets_provider(self):
        with patch("pipeline.ai_filter.PROVIDER_CONFIGS", {
            "test": {"api_key": "sk-test", "base_url": "https://test.api/v1"},
        }), patch("pipeline.ai_filter.PROVIDER_MODELS", {"test": "test-model"}):
            client = LLMClient("test")
            assert client.provider == "test"
            assert client.model == "test-model"


class TestAIFilter:
    @pytest.fixture
    def mock_filter(self):
        with patch("pipeline.ai_filter.PROVIDER_CONFIGS", {
            "mock": {"api_key": "sk-mock", "base_url": "https://mock.api/v1"},
        }), patch("pipeline.ai_filter.FALLBACK_CHAIN", ["mock"]), \
             patch("pipeline.ai_filter.PROVIDER_MODELS", {"mock": "mock-model"}):
            return AIFilter(batch_size=5)

    def test_filter_batch_parses_json_response(self, mock_filter):
        bios = [
            {"id": 1, "bio": "illustrator | commissions open"},
            {"id": 2, "bio": "software engineer"},
        ]
        mock_response = {
            "content": json.dumps([
                {"bio_id": 1, "result": "YES", "type": "content_creator", "confidence": 0.95},
                {"bio_id": 2, "result": "NO", "type": None, "confidence": 0.1},
            ]),
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }

        with patch.object(
            mock_filter._clients["mock"], "chat", new_callable=AsyncMock, return_value=mock_response
        ):
            results = asyncio.get_event_loop().run_until_complete(
                mock_filter.filter_batch(bios)
            )

        assert len(results) == 2
        assert results[0]["bio_id"] == 1
        assert results[0]["result"] == "YES"
        assert results[1]["bio_id"] == 2
        assert results[1]["result"] == "NO"

    def test_filter_batch_handles_markdown_fences(self, mock_filter):
        bios = [{"id": 1, "bio": "artist"}]
        fenced = "```json\n" + json.dumps([
            {"bio_id": 1, "result": "YES", "type": "content_creator", "confidence": 0.9}
        ]) + "\n```"
        mock_response = {
            "content": fenced,
            "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
        }

        with patch.object(
            mock_filter._clients["mock"], "chat", new_callable=AsyncMock, return_value=mock_response
        ):
            results = asyncio.get_event_loop().run_until_complete(
                mock_filter.filter_batch(bios)
            )

        assert len(results) == 1
        assert results[0]["result"] == "YES"

    def test_filter_batch_handles_invalid_json(self, mock_filter):
        bios = [{"id": 1, "bio": "test bio"}]
        mock_response = {
            "content": "This is not valid JSON at all",
            "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
        }

        with patch.object(
            mock_filter._clients["mock"], "chat", new_callable=AsyncMock, return_value=mock_response
        ):
            results = asyncio.get_event_loop().run_until_complete(
                mock_filter.filter_batch(bios)
            )

        assert len(results) == 1
        assert results[0]["result"] == "NO"
        assert results[0]["confidence"] == 0.0

    def test_empty_batch_returns_empty(self, mock_filter):
        results = asyncio.get_event_loop().run_until_complete(
            mock_filter.filter_batch([])
        )
        assert results == []

    def test_system_prompt_contains_key_signals(self):
        assert "linktr.ee" in SYSTEM_PROMPT
        assert "illustrator" in SYSTEM_PROMPT
        assert "commission open" in SYSTEM_PROMPT
        assert "Fan accounts" in SYSTEM_PROMPT
