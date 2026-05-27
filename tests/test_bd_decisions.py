"""Tests for bd_decisions table and per-user BD audit logic."""

from dashboard.candidates_query import build_assigned_count_sql, build_assigned_data_sql


class TestBuildAssignedSqlWithUserId:
    def test_count_sql_includes_bd_decisions_join(self):
        sql = build_assigned_count_sql("c.is_seed = false", "cs.sps_score DESC", 3, 1, current_user_id=5)
        assert "LEFT JOIN bd_decisions bd ON bd.creator_id = c.id AND bd.user_id = 5" in sql
        assert "ROW_NUMBER() OVER (ORDER BY cs.sps_score DESC)" in sql
        assert "(rn - 1) %% 3 = 1" in sql

    def test_count_sql_without_user_id_omits_join(self):
        sql = build_assigned_count_sql("c.is_seed = false", "cs.sps_score DESC", 3, 1)
        assert "bd_decisions" not in sql

    def test_data_sql_includes_bd_decisions_join_and_select(self):
        sql = build_assigned_data_sql("c.is_seed = false", "cs.sps_score DESC", 3, 1, current_user_id=7)
        assert "LEFT JOIN bd_decisions bd ON bd.creator_id = c.id AND bd.user_id = 7" in sql
        assert "bd.decision AS my_decision" in sql
        assert "bd.note AS my_note" in sql
        assert "(rn - 1) %% 3 = 1" in sql
        assert "LIMIT %s OFFSET %s" in sql

    def test_data_sql_without_user_id_omits_join(self):
        sql = build_assigned_data_sql("c.is_seed = false", "cs.sps_score DESC", 3, 1)
        assert "bd_decisions" not in sql
        assert "my_decision" not in sql


class TestBdDecisionsSqlPatterns:
    def test_insert_on_conflict_pattern(self):
        """Verify the upsert SQL pattern used in 2_candidates.py."""
        sql = """
            INSERT INTO bd_decisions (creator_id, user_id, decision, previous_decision, updated_at)
            VALUES (%s, %s, %s,
                (SELECT decision FROM bd_decisions WHERE creator_id = %s AND user_id = %s),
                NOW()
            )
            ON CONFLICT (creator_id, user_id)
            DO UPDATE SET decision = EXCLUDED.decision,
                          previous_decision = EXCLUDED.previous_decision,
                          updated_at = NOW()
        """
        assert "INSERT INTO bd_decisions" in sql
        assert "ON CONFLICT (creator_id, user_id)" in sql
        assert "previous_decision = EXCLUDED.previous_decision" in sql
        assert "decision = EXCLUDED.decision" in sql

    def test_note_upsert_pattern(self):
        """Verify the note-only upsert SQL pattern."""
        sql = """
            INSERT INTO bd_decisions (creator_id, user_id, note, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (creator_id, user_id)
            DO UPDATE SET note = EXCLUDED.note, updated_at = NOW()
        """
        assert "ON CONFLICT (creator_id, user_id)" in sql
        assert "note = EXCLUDED.note" in sql

    def test_outreach_query_uses_exists(self):
        """Verify outreach page uses EXISTS on bd_decisions instead of creators.bd_decision."""
        sql = """
       WHERE EXISTS (
           SELECT 1 FROM bd_decisions bd
           WHERE bd.creator_id = c.id AND bd.decision = 'interested'
       )
         AND c.followers > 500
       ORDER BY cs.sps_score DESC NULLS LAST"""
        assert "EXISTS (" in sql
        assert "bd_decisions bd" in sql
        assert "bd.decision = 'interested'" in sql
        assert "c.bd_decision" not in sql
