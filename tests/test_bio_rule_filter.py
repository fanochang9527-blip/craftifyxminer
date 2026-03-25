"""Unit tests for pipeline.bio_rule_filter — Level 1/2 BIO 规则快筛."""

import pytest

from pipeline.bio_rule_filter import BioRuleFilter


@pytest.fixture
def f():
    return BioRuleFilter()


# === Level 1: Link DNA ===

class TestLevel1LinkDNA:
    def test_linktr_ee_passes(self, f):
        r = f.filter("🎨 Artist | linktr.ee/myart")
        assert r["passed"] is True
        assert r["level"] == 1
        assert r["confidence"] >= 0.9

    def test_booth_pm_passes(self, f):
        r = f.filter("新作 booth.pm/items/12345")
        assert r["passed"] is True
        assert r["level"] == 1

    def test_artstation_passes(self, f):
        r = f.filter("Portfolio → artstation.com/user123")
        assert r["passed"] is True
        assert r["level"] == 1

    def test_etsy_shop_passes(self, f):
        r = f.filter("Handmade plushies etsy.com/shop/myplush")
        assert r["passed"] is True
        assert r["level"] == 1

    def test_multiple_links(self, f):
        r = f.filter("ko-fi.com/art | patreon.com/myart")
        assert r["passed"] is True
        assert "ko-fi.com" in r["signals"]

    def test_website_field_used(self, f):
        r = f.filter("Just an artist", website="https://pixiv.net/users/123")
        assert r["passed"] is True
        assert r["level"] == 1


# === Level 2: 语义矩阵 ===

class TestLevel2Semantic:
    def test_identity_illustrator(self, f):
        r = f.filter("Freelance illustrator | DMs open")
        assert r["passed"] is True
        assert r["level"] == 2
        assert "illustrator" in r["signals"]

    def test_identity_japanese(self, f):
        r = f.filter("絵師です。お仕事募集中")
        assert r["passed"] is True
        assert r["level"] == 2

    def test_identity_chinese(self, f):
        r = f.filter("自由插画师，欢迎约稿")
        assert r["passed"] is True

    def test_action_plus_tool(self, f):
        r = f.filter("commission open | Procreate & iPad")
        assert r["passed"] is True
        assert r["level"] == 2

    def test_weak_signals_two_hits(self, f):
        r = f.filter("I draw OC and fanart sometimes")
        assert r["passed"] is True
        assert r["level"] == 2

    def test_single_weak_signal_grey(self, f):
        r = f.filter("I love OC designs")
        # single weak signal + no other match → grey zone
        assert r["passed"] is None or r["passed"] is True

    def test_action_plus_emoji(self, f):
        r = f.filter("preorder now! 🎨")
        assert r["passed"] is True

    def test_tool_alone_not_enough(self, f):
        r = f.filter("I use Photoshop for photo editing")
        # Tool alone without action → grey zone
        assert r["passed"] is None


# === 误杀防范 ===

class TestFalsePositives:
    def test_fan_account_rejected(self, f):
        r = f.filter("fan account for @someartist | daily updates")
        assert r["passed"] is False
        assert "false_positive" in r["signals"]

    def test_stan_account_rejected(self, f):
        r = f.filter("stan account | stream on spotify")
        assert r["passed"] is False

    def test_studio_flagged(self, f):
        r = f.filter("We are a creative agency specializing in branding")
        assert r["passed"] is False


# === 灰区 (交给 LLM) ===

class TestGreyZone:
    def test_empty_bio(self, f):
        r = f.filter("")
        assert r["passed"] is None
        assert r["level"] == 0

    def test_unrelated_bio(self, f):
        r = f.filter("Software engineer at Google | Coffee lover")
        assert r["passed"] is None
        assert r["level"] == 0

    def test_ambiguous_bio(self, f):
        r = f.filter("Creating things I love ✨")
        # Has emoji but not enough signals
        assert r["passed"] is None or r["passed"] is True


# === 类型分类 ===

class TestTypeClassification:
    def test_oc_creator(self, f):
        r = f.filter("OC artist | linktr.ee/myoc")
        assert r["type"] == "oc_creator"

    def test_vtuber(self, f):
        r = f.filter("VTuber designer | Live2D | ko-fi.com/vt")
        assert r["type"] == "vtuber"

    def test_fan_artist(self, f):
        r = f.filter("fanart illustrator | booth.pm/fanart")
        assert r["type"] == "fan_artist"

    def test_game_creator(self, f):
        r = f.filter("indie game dev | pixiv.net/u/123")
        assert r["type"] == "game_creator"

    def test_default_content_creator(self, f):
        r = f.filter("Just creating art | gumroad.com/art")
        assert r["type"] == "content_creator"
