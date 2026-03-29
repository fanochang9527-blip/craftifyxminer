"""Unit tests for pipeline.ai_filter — Level 3 LLM Bio 过滤."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai import APIStatusError

from pipeline.ai_filter import AIFilter, LLMClient, SYSTEM_PROMPT, _is_non_retryable_auth_error, _parse_json_lenient


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

    def test_401_api_status_error_no_retry_second_provider(self):
        """DashScope 等兼容网关常抛 APIStatusError(401)，不应退避重试三次。"""
        req = httpx.Request("POST", "https://example.com/v1/chat/completions")
        resp = httpx.Response(401, request=req)
        err_401 = APIStatusError("invalid key", response=resp, body=None)

        with patch("pipeline.ai_filter.PROVIDER_CONFIGS", {
            "bad": {"api_key": "sk-bad", "base_url": "https://bad.example/v1"},
            "good": {"api_key": "sk-good", "base_url": "https://good.example/v1"},
        }), patch("pipeline.ai_filter.FALLBACK_CHAIN", ["bad", "good"]), \
             patch("pipeline.ai_filter.PROVIDER_MODELS", {"bad": "m1", "good": "m2"}):
            filt = AIFilter(batch_size=5)

        bios = [{"id": 1, "bio": "artist"}]
        mock_ok = {
            "content": json.dumps([
                {"bio_id": 1, "result": "YES", "type": "content_creator", "confidence": 0.9},
            ]),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        bad_chat = AsyncMock(side_effect=err_401)
        good_chat = AsyncMock(return_value=mock_ok)

        with patch.object(filt._clients["bad"], "chat", bad_chat), \
             patch.object(filt._clients["good"], "chat", good_chat):
            results = asyncio.get_event_loop().run_until_complete(filt.filter_batch(bios))

        assert bad_chat.await_count == 1
        assert good_chat.await_count == 1
        assert results[0]["result"] == "YES"


def test_is_non_retryable_auth_error_detects_api_status_401():
    req = httpx.Request("POST", "https://x")
    e = APIStatusError("x", response=httpx.Response(401, request=req), body=None)
    assert _is_non_retryable_auth_error(e) is True


class TestParseJsonLenient:
    def test_valid_json(self):
        text = '[{"bio_id": 1, "result": "YES"}]'
        assert _parse_json_lenient(text) == [{"bio_id": 1, "result": "YES"}]

    def test_truncated_json_salvages_complete_objects(self):
        text = '[{"bio_id": 1, "result": "YES"}, {"bio_id": 2, "result": "NO"}, {"bio_id": 3, "res'
        result = _parse_json_lenient(text)
        assert len(result) == 2
        assert result[0]["bio_id"] == 1
        assert result[1]["bio_id"] == 2

    def test_empty_string_returns_none(self):
        assert _parse_json_lenient("") is None

    def test_completely_invalid_returns_none(self):
        assert _parse_json_lenient("not json at all") is None
