"""Unit tests for pipeline.type_classifier — classify_creator (no DB)."""

import sys
from unittest.mock import MagicMock

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from pipeline.type_classifier import classify_creator


class TestClassifyCreator:
    def test_bio_oc_keywords(self):
        assert classify_creator("my OC art | original character", "") == "oc_creator"

    def test_bio_vtuber(self):
        assert classify_creator("VTuber designer | Live2D | ko-fi.com/vt", "") == "vtuber"

    def test_tweets_fanart(self):
        assert classify_creator("", "", tweets_text="Check this #fanart piece!") == "fan_artist"

    def test_tweets_gamedev(self):
        assert classify_creator("", "", tweets_text="New build #gamedev #indiedev") == "game_creator"

    def test_empty_bio_and_tweets_unknown(self):
        assert classify_creator("", "", "") == "unknown"
