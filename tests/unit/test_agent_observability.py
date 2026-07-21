"""Tests for the Command Center observability stats (runs + cost window)."""

from __future__ import annotations


class TestObservabilityStats:
    def _seed_agent_with_activity(self, test_database, test_user):
        agent = test_database.create_agent(user_id=test_user.id, name="Obs")
        e1 = test_database.create_execution(agent.id, "scheduled")
        test_database.update_execution(e1.id, status="completed")
        e2 = test_database.create_execution(agent.id, "manual")
        test_database.update_execution(e2.id, status="failed")
        # Cost attributed via the agent's dedicated conversation
        msg = test_database.add_message(agent.conversation_id, "assistant", "report")
        test_database.save_message_cost(
            message_id=msg.id,
            conversation_id=agent.conversation_id,
            user_id=test_user.id,
            model="gemini-3.6-flash",
            input_tokens=1000,
            output_tokens=200,
            cost_usd=0.05,
        )
        return agent

    def test_aggregates_runs_and_costs(self, test_database, test_user) -> None:
        agent = self._seed_agent_with_activity(test_database, test_user)

        stats = test_database.get_agent_observability_stats(test_user.id, days=7)
        assert stats["days"] == 7
        agent_stats = stats["per_agent"][agent.id]
        assert agent_stats["runs"] == 2
        assert agent_stats["completed"] == 1
        assert agent_stats["failed"] == 1
        assert agent_stats["cost_usd"] == 0.05
        assert agent_stats["input_tokens"] == 1000
        assert agent_stats["output_tokens"] == 200

    def test_window_excludes_old_activity(self, test_database, test_user) -> None:
        agent = self._seed_agent_with_activity(test_database, test_user)
        # Age all activity beyond the window
        with test_database._pool.get_connection() as conn:
            conn.execute(
                "UPDATE agent_executions SET started_at = '2026-01-01T00:00:00' WHERE agent_id = ?",
                (agent.id,),
            )
            conn.execute(
                "UPDATE message_costs SET created_at = '2026-01-01T00:00:00' WHERE user_id = ?",
                (test_user.id,),
            )
            conn.commit()

        stats = test_database.get_agent_observability_stats(test_user.id, days=7)
        assert agent.id not in stats["per_agent"]

    def test_no_activity_returns_empty(self, test_database, test_user) -> None:
        stats = test_database.get_agent_observability_stats(test_user.id, days=7)
        assert stats["per_agent"] == {}


class TestCommandCenterStatsBlock:
    def test_response_includes_stats(self, client, auth_headers, test_database, test_user) -> None:
        agent = test_database.create_agent(user_id=test_user.id, name="Obs")
        execution = test_database.create_execution(agent.id, "scheduled")
        test_database.update_execution(execution.id, status="completed")

        response = client.get("/api/agents/command-center", headers=auth_headers)
        assert response.status_code == 200
        stats = response.get_json()["stats"]
        assert stats["days"] == 7
        assert stats["total_runs"] == 1
        assert stats["total_completed"] == 1
        assert stats["total_failed"] == 0
        assert stats["total_cost_display"]
        per_agent = {s["agent_id"]: s for s in stats["per_agent"]}
        assert per_agent[agent.id]["runs"] == 1
