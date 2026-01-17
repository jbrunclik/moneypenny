"""Shared scheduler logic for autonomous agents.

This module provides the core scheduling logic used by both:
- Production: systemd timer script (scripts/run_agent_scheduler.py)
- Development: background thread (src/agent/dev_scheduler.py)

The only difference between environments is how the scheduler is triggered:
- Production: External systemd timer invokes the script every minute
- Development: Internal background thread calls run_scheduled_agents() every minute
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.db.models import db
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models.dataclasses import Agent

logger = get_logger(__name__)


@dataclass
class SchedulerResult:
    """Result of a scheduler run."""

    executed: int = 0
    skipped: int = 0
    failed: int = 0
    waiting_approval: int = 0


def run_scheduled_agents() -> SchedulerResult:
    """Execute all agents that are due to run.

    This is the shared core logic used by both production (systemd timer)
    and development (background thread) schedulers.

    Returns:
        SchedulerResult with counts of executed, skipped, and failed agents.
    """
    from src.agent.executor import AgentBlockedError, execute_agent
    from src.agent.tools.request_approval import ApprovalRequestedException

    now = datetime.now(UTC).replace(tzinfo=None)  # Naive UTC for DB comparison
    logger.info("Scheduler: evaluating agent schedules", extra={"now": now.isoformat()})

    # Clean up zombie executions (stuck in running/waiting_approval for too long)
    zombies_cleaned = db.cleanup_zombie_executions()
    if zombies_cleaned > 0:
        logger.warning(
            "Scheduler: cleaned up zombie executions",
            extra={"count": zombies_cleaned},
        )

    # Get agents due for execution (enabled, has schedule, next_run_at <= now)
    due_agents = db.get_due_agents(now)
    logger.info(
        "Scheduler: found due agents",
        extra={"count": len(due_agents), "agent_ids": [a.id for a in due_agents]},
    )

    result = SchedulerResult()

    for agent in due_agents:
        # Skip agents with pending approval
        if db.has_pending_approval(agent.id):
            logger.debug(
                "Scheduler: skipping agent with pending approval",
                extra={"agent_id": agent.id, "agent_name": agent.name},
            )
            result.skipped += 1
            continue

        # Skip agents that are already running (prevent overlapping executions)
        if db.has_running_execution(agent.id):
            logger.debug(
                "Scheduler: skipping agent with running execution",
                extra={"agent_id": agent.id, "agent_name": agent.name},
            )
            result.skipped += 1
            continue

        # Get the user
        user = db.get_user_by_id(agent.user_id)
        if not user:
            logger.warning(
                "Scheduler: user not found for agent",
                extra={"agent_id": agent.id, "user_id": agent.user_id},
            )
            result.failed += 1
            continue

        # Create execution record
        execution = db.create_execution(
            agent_id=agent.id,
            trigger_type="scheduled",
        )

        try:
            logger.info(
                "Scheduler: executing agent",
                extra={"agent_id": agent.id, "agent_name": agent.name},
            )

            # Execute the agent
            exec_result, error_msg = execute_agent(agent, user, "scheduled", execution.id)

            if exec_result is True:
                db.update_execution(execution.id, status="completed")
                result.executed += 1
                logger.info(
                    "Scheduler: agent execution completed",
                    extra={"agent_id": agent.id, "agent_name": agent.name},
                )
            elif exec_result == "waiting_approval":
                # Executor already set status to waiting_approval
                result.waiting_approval += 1
                logger.info(
                    "Scheduler: agent waiting for approval",
                    extra={"agent_id": agent.id, "agent_name": agent.name},
                )
            else:
                db.update_execution(execution.id, status="failed", error_message=error_msg)
                result.failed += 1
                logger.warning(
                    "Scheduler: agent execution failed",
                    extra={"agent_id": agent.id, "error": error_msg},
                )
                _update_next_run_on_failure(agent)

        except ApprovalRequestedException:
            # Agent used request_approval tool - already handled by executor
            result.waiting_approval += 1
            logger.info(
                "Scheduler: agent requested approval",
                extra={"agent_id": agent.id, "agent_name": agent.name},
            )

        except AgentBlockedError as e:
            result.skipped += 1
            logger.warning(
                "Scheduler: agent blocked",
                extra={"agent_id": agent.id, "error": str(e)},
            )

        except Exception as e:
            db.update_execution(execution.id, status="failed", error_message=str(e))
            result.failed += 1
            logger.error(
                "Scheduler: agent execution error",
                extra={"agent_id": agent.id, "error": str(e)},
                exc_info=True,
            )
            _update_next_run_on_failure(agent)

    logger.info(
        "Scheduler: completed",
        extra={
            "executed": result.executed,
            "skipped": result.skipped,
            "failed": result.failed,
            "waiting_approval": result.waiting_approval,
        },
    )

    return result


def _update_next_run_on_failure(agent: Agent) -> None:
    """Update next_run_at after a failed execution.

    On success, execute_agent() updates next_run_at via update_agent_last_run().
    On failure, we need to manually advance the schedule to prevent retry loops.
    """
    if agent.schedule:
        next_run = db.calculate_next_run(agent.schedule, agent.timezone)
        if next_run:
            db.update_agent_next_run(agent.id, next_run)
            logger.debug(
                "Scheduler: updated next_run_at after failure",
                extra={"agent_id": agent.id, "next_run": next_run.isoformat()},
            )
