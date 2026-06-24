"""Unit tests for pipeline.project_import helpers."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

for mod_name in ("psycopg2", "psycopg2.pool", "psycopg2.extras"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from pipeline.project_import import _generate_project_id


class TestGenerateProjectId:
    def test_deterministic(self):
        sku = "H-001 | 77-00001"
        id1 = _generate_project_id(sku)
        id2 = _generate_project_id(sku)
        assert id1 == id2
        assert len(id1) == 16

    def test_different_skus_different_ids(self):
        id1 = _generate_project_id("H-001")
        id2 = _generate_project_id("H-002")
        assert id1 != id2
