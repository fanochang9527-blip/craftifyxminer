"""Unit tests for pipeline.content_style_filter — multimodal content style filtering.

Business context: creators are evaluated for plush-toy suitability.
- Realistic style -> REJECTED (uncanny valley, poor sales)
- Fixed/recurring character IP -> PASSED (sustainable merch potential)
- Final pass condition: NOT realistic AND has_fixed_ip AND confidence >= threshold
"""

import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from pipeline.content_style_filter import ContentStyleFilter, filter_all_pending


class TestParseResult:
    def test_valid_json(self):
        filt = ContentStyleFilter()
        result = filt._parse_result('{"is_realistic": true, "has_fixed_ip": false, "confidence": 0.85}')
        assert result == {"is_realistic": True, "has_fixed_ip": False, "confidence": 0.85}

    def test_markdown_fenced_json(self):
        filt = ContentStyleFilter()
        text = "```json\n{\"is_realistic\": true, \"has_fixed_ip\": true, \"confidence\": 0.9}\n```"
        result = filt._parse_result(text)
        assert result == {"is_realistic": True, "has_fixed_ip": True, "confidence": 0.9}

    def test_invalid_json_returns_none(self):
        filt = ContentStyleFilter()
        assert filt._parse_result("not json at all") is None

    def test_partial_json_extraction(self):
        filt = ContentStyleFilter()
        text = 'some text before {"is_realistic": true, "has_fixed_ip": true, "confidence": 0.9} some after'
        result = filt._parse_result(text)
        assert result == {"is_realistic": True, "has_fixed_ip": True, "confidence": 0.9}

    def test_empty_string_returns_none(self):
        filt = ContentStyleFilter()
        assert filt._parse_result("") is None


class TestBuildMessages:
    @patch("pipeline.content_style_filter.PROVIDER_CONFIGS", {"mock": {"api_key": "sk-mock", "base_url": "https://mock.api/v1"}})
    @patch("pipeline.content_style_filter.CONTENT_STYLE_FALLBACK_CHAIN", ["mock"])
    def test_build_messages_contains_vision_format(self):
        filt = ContentStyleFilter()
        tweets = [
            {
                "text": "My latest artwork!",
                "media_urls": ["https://pbs.twimg.com/media/abc.jpg"],
                "media_types": ["photo"],
            },
            {
                "text": "Another piece",
                "media_urls": ["https://pbs.twimg.com/media/def.jpg", "https://pbs.twimg.com/media/ghi.jpg"],
                "media_types": ["photo", "photo"],
            },
        ]
        messages = filt._build_messages("testuser", tweets)

        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

        content = messages[1]["content"]
        assert isinstance(content, list)

        # 第一个 element 是文本 intro
        assert content[0]["type"] == "text"
        assert "testuser" in content[0]["text"]

        # 后续是 image_url
        image_parts = [c for c in content if c["type"] == "image_url"]
        assert len(image_parts) == 3
        assert image_parts[0]["image_url"]["url"] == "https://pbs.twimg.com/media/abc.jpg"

    def test_build_messages_respects_max_media(self):
        with patch("pipeline.content_style_filter.PROVIDER_CONFIGS", {"mock": {"api_key": "sk-mock", "base_url": "https://mock.api/v1"}}), \
             patch("pipeline.content_style_filter.CONTENT_STYLE_FALLBACK_CHAIN", ["mock"]), \
             patch("pipeline.content_style_filter.CONTENT_STYLE_MAX_MEDIA_PER_CREATOR", 2):
            filt = ContentStyleFilter()
            tweets = [
                {"text": "t1", "media_urls": ["https://a/1.jpg", "https://a/2.jpg"], "media_types": ["photo", "photo"]},
                {"text": "t2", "media_urls": ["https://a/3.jpg"], "media_types": ["photo"]},
            ]
            messages = filt._build_messages("user", tweets)
            content = messages[1]["content"]
            image_parts = [c for c in content if c["type"] == "image_url"]
            assert len(image_parts) == 2


class TestAnalyzeOne:
    @pytest.fixture
    def mock_filter(self):
        with patch("pipeline.content_style_filter.PROVIDER_CONFIGS", {
            "mock": {"api_key": "sk-mock", "base_url": "https://mock.api/v1"},
        }), patch("pipeline.content_style_filter.CONTENT_STYLE_FALLBACK_CHAIN", ["moonshot"]), \
             patch("pipeline.content_style_filter.PROVIDER_MODELS", {"moonshot": "mock-vision-model"}), \
             patch("pipeline.content_style_filter.CONTENT_STYLE_LLM_PROVIDER", "moonshot"), \
             patch("pipeline.content_style_filter.CONTENT_STYLE_LLM_MODEL", "mock-vision-model"):
            filt = ContentStyleFilter()
            filt.max_media = 5
            filt.max_tweets = 10
            filt.confidence_threshold = 0.7
            return filt

    # ------------------------------------------------------------------
    # 通过场景：非写实 + 固定IP
    # ------------------------------------------------------------------

    def test_passes_when_not_realistic_and_has_fixed_ip(self, mock_filter):
        """卡通/动漫风格 + 固定角色 = 最佳，应通过。"""
        creator = {"id": 1, "username": "artist1"}
        tweets = [
            {"text": "art", "media_urls": ["https://a/1.jpg"], "media_types": ["photo"]},
        ]
        mock_response = {
            "content": json.dumps({"is_realistic": False, "has_fixed_ip": True, "confidence": 0.9, "reason": "cute chibi style with recurring character"}),
            "usage": {"total_tokens": 200},
            "_provider": "moonshot",
            "_model": "mock-vision-model",
        }

        with patch("pipeline.content_style_filter.fetch_all", return_value=tweets), \
             patch.object(mock_filter, "_call_with_retry", new_callable=AsyncMock, return_value=mock_response):
            result = asyncio.get_event_loop().run_until_complete(mock_filter._analyze_one(creator))

        assert result["status"] == "analyzed"
        assert result["is_realistic"] is False
        assert result["has_fixed_ip"] is True
        assert result["confidence"] == 0.9
        assert result["passed"] is True
        assert result["model_used"] == "moonshot/mock-vision-model"
        assert result["media_sample"] == ["https://a/1.jpg"]

    # ------------------------------------------------------------------
    # URL 不被识别时自动转 base64 重试
    # ------------------------------------------------------------------

    def test_fallback_to_base64_on_unsupported_url(self, mock_filter):
        """Moonshot 不识别外部图片 URL 时，应下载并转 base64 重试。"""
        creator = {"id": 10, "username": "artist10"}
        tweets = [
            {"text": "art", "media_urls": ["https://a/10.jpg"], "media_types": ["photo"]},
        ]
        mock_response = {
            "content": json.dumps({"is_realistic": False, "has_fixed_ip": True, "confidence": 0.9, "reason": "cute"}),
            "usage": {"total_tokens": 200},
            "_provider": "moonshot",
            "_model": "mock-vision-model",
        }
        unsupported_error = Exception("Invalid request: unsupported image url: https://a/10.jpg")

        with patch("pipeline.content_style_filter.fetch_all", return_value=tweets), \
             patch.object(mock_filter, "_call_with_retry", new_callable=AsyncMock, side_effect=[unsupported_error, mock_response]) as mock_call, \
             patch("pipeline.content_style_filter._download_image_async", new_callable=AsyncMock, return_value=(b"fakebytes", "image/jpeg")):
            result = asyncio.get_event_loop().run_until_complete(mock_filter._analyze_one(creator))

        assert result["status"] == "analyzed"
        assert result["passed"] is True
        assert mock_call.call_count == 2
        # 第二次调用应使用 base64 data URL
        second_messages = mock_call.call_args_list[1].args[0]
        image_parts = [c for c in second_messages[1]["content"] if c["type"] == "image_url"]
        assert len(image_parts) == 1
        assert image_parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_no_base64_fallback_for_non_image_error(self, mock_filter):
        """非图片类 API 错误不应触发下载转 base64。"""
        creator = {"id": 11, "username": "artist11"}
        tweets = [
            {"text": "art", "media_urls": ["https://a/11.jpg"], "media_types": ["photo"]},
        ]
        auth_error = Exception("401 Authentication failed")

        with patch("pipeline.content_style_filter.fetch_all", return_value=tweets), \
             patch.object(mock_filter, "_call_with_retry", new_callable=AsyncMock, side_effect=auth_error) as mock_call, \
             patch("pipeline.content_style_filter._download_image_async", new_callable=AsyncMock) as mock_download:
            result = asyncio.get_event_loop().run_until_complete(mock_filter._analyze_one(creator))

        assert result["status"] == "failed"
        assert mock_call.call_count == 1
        mock_download.assert_not_called()

    def test_base64_retry_failure_returns_failed(self, mock_filter):
        """URL 不识别且 base64 重试也失败时，应返回 failed。"""
        creator = {"id": 12, "username": "artist12"}
        tweets = [
            {"text": "art", "media_urls": ["https://a/12.jpg"], "media_types": ["photo"]},
        ]
        unsupported_error = Exception("Invalid request: unsupported image url: https://a/12.jpg")
        retry_error = Exception("still fails after base64")

        with patch("pipeline.content_style_filter.fetch_all", return_value=tweets), \
             patch.object(mock_filter, "_call_with_retry", new_callable=AsyncMock, side_effect=[unsupported_error, retry_error]), \
             patch("pipeline.content_style_filter._download_image_async", new_callable=AsyncMock, return_value=(b"fakebytes", "image/jpeg")):
            result = asyncio.get_event_loop().run_until_complete(mock_filter._analyze_one(creator))

        assert result["status"] == "failed"

    # ------------------------------------------------------------------
    # 拒绝场景 1：写实风格（无论有没有固定IP）
    # ------------------------------------------------------------------

    def test_rejects_when_realistic_and_has_fixed_ip(self, mock_filter):
        """写实风格 + 固定IP = 不适合毛绒娃娃（恐怖谷），应拒绝。"""
        creator = {"id": 2, "username": "artist2"}
        tweets = [
            {"text": "realistic portrait", "media_urls": ["https://a/2.jpg"], "media_types": ["photo"]},
        ]
        mock_response = {
            "content": json.dumps({"is_realistic": True, "has_fixed_ip": True, "confidence": 0.9, "reason": "hyper-realistic style"}),
            "usage": {"total_tokens": 200},
            "_provider": "moonshot",
            "_model": "mock-vision-model",
        }

        with patch("pipeline.content_style_filter.fetch_all", return_value=tweets), \
             patch.object(mock_filter, "_call_with_retry", new_callable=AsyncMock, return_value=mock_response):
            result = asyncio.get_event_loop().run_until_complete(mock_filter._analyze_one(creator))

        assert result["status"] == "analyzed"
        assert result["is_realistic"] is True
        assert result["has_fixed_ip"] is True
        assert result["passed"] is False
        assert result["model_used"] == "moonshot/mock-vision-model"

    def test_rejects_when_realistic_and_no_fixed_ip(self, mock_filter):
        """写实风格 + 无固定IP = 应拒绝。"""
        creator = {"id": 3, "username": "artist3"}
        tweets = [
            {"text": "realistic art", "media_urls": ["https://a/3.jpg"], "media_types": ["photo"]},
        ]
        mock_response = {
            "content": json.dumps({"is_realistic": True, "has_fixed_ip": False, "confidence": 0.85, "reason": "realistic landscapes, no recurring character"}),
            "usage": {"total_tokens": 200},
            "_provider": "moonshot",
            "_model": "mock-vision-model",
        }

        with patch("pipeline.content_style_filter.fetch_all", return_value=tweets), \
             patch.object(mock_filter, "_call_with_retry", new_callable=AsyncMock, return_value=mock_response):
            result = asyncio.get_event_loop().run_until_complete(mock_filter._analyze_one(creator))

        assert result["status"] == "analyzed"
        assert result["is_realistic"] is True
        assert result["has_fixed_ip"] is False
        assert result["passed"] is False

    # ------------------------------------------------------------------
    # 拒绝场景 2：无固定IP（无论是否写实）
    # ------------------------------------------------------------------

    def test_rejects_when_not_realistic_but_no_fixed_ip(self, mock_filter):
        """非写实 + 无固定IP = 无法持续出周边，应拒绝。"""
        creator = {"id": 4, "username": "artist4"}
        tweets = [
            {"text": "random doodles", "media_urls": ["https://a/4.jpg"], "media_types": ["photo"]},
        ]
        mock_response = {
            "content": json.dumps({"is_realistic": False, "has_fixed_ip": False, "confidence": 0.8, "reason": "varied random doodles, no recurring character"}),
            "usage": {"total_tokens": 200},
            "_provider": "moonshot",
            "_model": "mock-vision-model",
        }

        with patch("pipeline.content_style_filter.fetch_all", return_value=tweets), \
             patch.object(mock_filter, "_call_with_retry", new_callable=AsyncMock, return_value=mock_response):
            result = asyncio.get_event_loop().run_until_complete(mock_filter._analyze_one(creator))

        assert result["status"] == "analyzed"
        assert result["is_realistic"] is False
        assert result["has_fixed_ip"] is False
        assert result["passed"] is False

    # ------------------------------------------------------------------
    # 拒绝场景 3：置信度不足
    # ------------------------------------------------------------------

    def test_rejects_when_low_confidence(self, mock_filter):
        """非写实 + 固定IP 但 confidence 低 = 宁可错杀，应拒绝。"""
        creator = {"id": 5, "username": "artist5"}
        tweets = [
            {"text": "art", "media_urls": ["https://a/5.jpg"], "media_types": ["photo"]},
        ]
        mock_response = {
            "content": json.dumps({"is_realistic": False, "has_fixed_ip": True, "confidence": 0.5, "reason": "maybe a recurring character but hard to tell"}),
            "usage": {"total_tokens": 200},
            "_provider": "moonshot",
            "_model": "mock-vision-model",
        }

        with patch("pipeline.content_style_filter.fetch_all", return_value=tweets), \
             patch.object(mock_filter, "_call_with_retry", new_callable=AsyncMock, return_value=mock_response):
            result = asyncio.get_event_loop().run_until_complete(mock_filter._analyze_one(creator))

        assert result["passed"] is False
        assert result["confidence"] == 0.5

    # ------------------------------------------------------------------
    # 边缘场景
    # ------------------------------------------------------------------

    def test_skips_no_media(self, mock_filter):
        creator = {"id": 6, "username": "artist6"}

        with patch("pipeline.content_style_filter.fetch_all", return_value=[]):
            result = asyncio.get_event_loop().run_until_complete(mock_filter._analyze_one(creator))

        assert result["status"] == "skipped_no_media"
        assert result["model_used"] is None

    def test_handles_parse_failure(self, mock_filter):
        creator = {"id": 7, "username": "artist7"}
        tweets = [
            {"text": "art", "media_urls": ["https://a/7.jpg"], "media_types": ["photo"]},
        ]
        mock_response = {
            "content": "this is not valid json",
            "usage": {"total_tokens": 100},
            "_provider": "moonshot",
            "_model": "mock-vision-model",
        }

        with patch("pipeline.content_style_filter.fetch_all", return_value=tweets), \
             patch.object(mock_filter, "_call_with_retry", new_callable=AsyncMock, return_value=mock_response):
            result = asyncio.get_event_loop().run_until_complete(mock_filter._analyze_one(creator))

        assert result["status"] == "failed"
        assert result["model_used"] == "moonshot/mock-vision-model"


class TestWriteResults:
    @patch("pipeline.content_style_filter.get_cursor")
    def test_failed_updates_bd_status_to_content_rejected(self, mock_get_cursor):
        """多模态分析失败时，必须将 creators.bd_status 更新为 content_rejected，
        防止失败创作者仍以 ai_passed/rule_passed 出现在前端。"""
        from pipeline.content_style_filter import _write_results

        mock_cur = MagicMock()
        mock_get_cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        results = [
            {
                "creator_id": 42,
                "status": "failed",
                "model_used": "mock/mock-model",
            }
        ]

        stats = _write_results(results)
        assert stats["failed"] == 1

        # 验证 UPDATE creators 被执行
        execute_calls = [call for call in mock_cur.execute.call_args_list]
        update_calls = [c for c in execute_calls if "UPDATE creators SET bd_status" in str(c)]
        assert len(update_calls) == 1
        assert "content_rejected" in str(update_calls[0])

    @patch("pipeline.content_style_filter.get_cursor")
    def test_rejected_updates_bd_status_to_content_rejected(self, mock_get_cursor):
        """多模态分析判定不通过时，bd_status 更新为 content_rejected。"""
        from pipeline.content_style_filter import _write_results

        mock_cur = MagicMock()
        mock_get_cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        results = [
            {
                "creator_id": 43,
                "status": "analyzed",
                "passed": False,
                "is_realistic": True,
                "has_fixed_ip": False,
                "confidence": 0.9,
                "model_used": "mock/mock-model",
                "raw_result": {"is_realistic": True, "has_fixed_ip": False},
                "media_sample": ["https://a/1.jpg"],
            }
        ]

        stats = _write_results(results)
        assert stats["rejected"] == 1

        execute_calls = [call for call in mock_cur.execute.call_args_list]
        update_calls = [c for c in execute_calls if "UPDATE creators SET bd_status" in str(c)]
        assert len(update_calls) == 1
        assert "content_rejected" in str(update_calls[0])

    @patch("pipeline.content_style_filter.get_cursor")
    def test_passed_does_not_change_bd_status(self, mock_get_cursor):
        """多模态分析通过时，bd_status 保持不变。"""
        from pipeline.content_style_filter import _write_results

        mock_cur = MagicMock()
        mock_get_cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_get_cursor.return_value.__exit__ = MagicMock(return_value=False)

        results = [
            {
                "creator_id": 44,
                "status": "analyzed",
                "passed": True,
                "is_realistic": False,
                "has_fixed_ip": True,
                "confidence": 0.9,
                "model_used": "mock/mock-model",
                "raw_result": {"is_realistic": False, "has_fixed_ip": True},
                "media_sample": ["https://a/1.jpg"],
            }
        ]

        stats = _write_results(results)
        assert stats["passed"] == 1

        execute_calls = [call for call in mock_cur.execute.call_args_list]
        update_calls = [c for c in execute_calls if "UPDATE creators SET bd_status" in str(c)]
        assert len(update_calls) == 0


class TestFilterAllPending:
    @patch("pipeline.content_style_filter.CONTENT_STYLE_ENABLED", False)
    def test_disabled_returns_zero(self):
        result = filter_all_pending()
        assert result["disabled"] is True
        assert result["analyzed"] == 0

    @patch("pipeline.content_style_filter.CONTENT_STYLE_ENABLED", True)
    @patch("pipeline.content_style_filter.fetch_all", return_value=[])
    def test_no_pending_returns_zero(self, _mock_fetch):
        result = filter_all_pending()
        assert result == {"analyzed": 0, "passed": 0, "rejected": 0, "skipped": 0, "failed": 0}
