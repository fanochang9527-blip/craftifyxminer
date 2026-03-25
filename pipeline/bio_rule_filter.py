"""Level 1/2 BIO 规则快筛 — 零 LLM 成本, 覆盖 ~70% 明确 case。

加载 config/bio_rules.yaml, 依次执行:
  Level 1: Link DNA 指纹匹配 (高置信 → 直接 YES)
  Level 2: 语义矩阵 (身份/动作/工具/弱信号 + Emoji) + 误杀防范
  未命中 → passed=None, 交给 Level 3 LLM
"""

import re
import logging
from pathlib import Path

import yaml

from config.settings import BIO_RULES_PATH

logger = logging.getLogger(__name__)


class BioRuleFilter:
    """Level 1/2 规则快筛: 零 LLM 成本, 处理 ~70% 的明确 case。"""

    def __init__(self, rules_path: str | Path | None = None):
        path = Path(rules_path) if rules_path else BIO_RULES_PATH
        with open(path, encoding="utf-8") as f:
            self.rules = yaml.safe_load(f)
        self._compile()

    # ------------------------------------------------------------------
    # 预编译
    # ------------------------------------------------------------------
    def _compile(self):
        sm = self.rules.get("semantic_matrix", {})

        self._identity_keywords: list[str] = []
        for lang_list in sm.get("identity_keywords", {}).values():
            self._identity_keywords.extend(kw.lower() for kw in lang_list)

        self._action_keywords: list[str] = []
        for lang_list in sm.get("action_keywords", {}).values():
            self._action_keywords.extend(kw.lower() for kw in lang_list)

        self._tool_keywords = [kw.lower() for kw in sm.get("tool_keywords", [])]
        self._weak_signals = [kw.lower() for kw in sm.get("weak_signals", [])]

        emoji_cfg = self.rules.get("emoji_signals", {})
        self._all_emojis: list[str] = []
        for group in emoji_cfg.values():
            self._all_emojis.extend(group)

        fp = self.rules.get("false_positive_rules", {})
        self._fan_signals = [s.lower() for s in fp.get("fan_account_signals", [])]
        self._studio_signals = [s.lower() for s in fp.get("studio_signals", [])]

        tc = self.rules.get("type_classification", {})
        self._type_keywords: dict[str, list[str]] = {
            ctype: [kw.lower() for kw in kws] for ctype, kws in tc.items()
        }

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------
    def filter(self, bio: str, website: str = "") -> dict:
        """Run Level 1 + Level 2 rule filters on a single bio.

        Returns:
            {"passed": True|False|None, "level": 1|2|0,
             "type": str|None, "confidence": float, "signals": list[str]}
        """
        text = f"{bio} {website}".lower()

        # --- Level 1: Link DNA ---
        link_signals = [d for d in self.rules["link_dna"]["high_confidence"] if d in text]
        if link_signals:
            return {
                "passed": True,
                "level": 1,
                "type": self._classify_type(text),
                "confidence": 0.95,
                "signals": link_signals,
            }

        # Medium-confidence links need a second signal
        medium_links = [d for d in self.rules["link_dna"].get("medium_confidence", []) if d in text]

        # --- Level 2: 语义矩阵 ---

        # False-positive check runs BEFORE keyword matching to avoid
        # "fan account for @artist" triggering the identity-keyword path.
        if self._is_false_positive(text):
            return {
                "passed": False,
                "level": 2,
                "type": None,
                "confidence": 0.85,
                "signals": ["false_positive"],
            }

        identity_hits = self._match(text, self._identity_keywords)
        action_hits = self._match(text, self._action_keywords)
        tool_hits = self._match(text, self._tool_keywords)
        weak_hits = self._match(text, self._weak_signals)
        emoji_hits = self._match_emojis(bio)

        # 身份类命中 → 直接 YES
        if identity_hits:
            return {
                "passed": True,
                "level": 2,
                "type": self._classify_type(text),
                "confidence": 0.90,
                "signals": identity_hits,
            }

        # 动作+工具 or 弱信号 2+ or 动作+emoji or medium_link+任意信号
        combined = action_hits + tool_hits + weak_hits + emoji_hits
        if (action_hits and tool_hits) or len(weak_hits) >= 2 or (action_hits and emoji_hits):
            return {
                "passed": True,
                "level": 2,
                "type": self._classify_type(text),
                "confidence": 0.80,
                "signals": combined,
            }

        if medium_links and combined:
            return {
                "passed": True,
                "level": 2,
                "type": self._classify_type(text),
                "confidence": 0.75,
                "signals": medium_links + combined,
            }

        # 规则未命中 → 交给 Level 3 LLM
        return {
            "passed": None,
            "level": 0,
            "type": None,
            "confidence": 0.0,
            "signals": weak_hits + emoji_hits,
        }

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _match(text: str, keywords: list[str]) -> list[str]:
        return [kw for kw in keywords if kw in text]

    def _match_emojis(self, bio: str) -> list[str]:
        return [e for e in self._all_emojis if e in bio]

    def _is_false_positive(self, text: str) -> bool:
        for sig in self._fan_signals:
            if sig in text:
                return True
        for sig in self._studio_signals:
            if sig in text:
                return True
        return False

    def _classify_type(self, text: str) -> str:
        for ctype, keywords in self._type_keywords.items():
            if any(kw in text for kw in keywords):
                return ctype
        return "content_creator"
