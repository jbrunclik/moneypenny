# Scheduled Jobs

The application uses **one** mechanism for time-scheduled work. There is no in-process
job scheduler and no periodic daemon thread started at app boot in production.

- **Production**: systemd user timers — a `.service` + `.timer` pair per job.
- **Development**: a single `dev_scheduler` background loop that stands in for the timers.

## The Rule

> Never start scheduler threads or daemon threads in `create_app()` for scheduled work.

Time-scheduled work runs from systemd timers in production and from the `dev_scheduler`
loop in development. Do not add a `threading.Timer`, an in-process cron, or a
"tick every N seconds" daemon thread to the web application to run scheduled jobs.

### Why systemd Timers

- **`journalctl` logging** — each job's output is captured per-unit (`journalctl --user -u <unit>`).
- **Guaranteed single execution** — production runs multiple gunicorn workers; a timer
  fires the job exactly once, avoiding per-worker duplicate runs and the kv-store
  stamp locking that in-process schedulers would need to coordinate.
- **Catch-up after downtime** — `Persistent=true` runs a missed job on next boot.
- **Independent of worker lifecycle** — jobs don't depend on gunicorn workers being alive,
  restarting, or recycling.

### Event-Driven Threads Are Fine

The rule applies only to *time-scheduled* work. Threads that respond to an event
(background thumbnail generation, web-push sends, conversation compaction) are fine
in-process — they are triggered by a request or a message, not by the clock.

## Production: systemd Timers

Each job is:

1. A runnable script in [`scripts/`](../../scripts/).
2. A `.service` (oneshot) + `.timer` pair in [`systemd/`](../../systemd/).
3. Wired into the Makefile `deploy` target (copies units to `~/.config/systemd/user/`,
   then `daemon-reload` / `enable` / `start`).

Timers are installed and started by `make deploy`. Check status and logs:

```bash
systemctl --user list-timers            # See all timers and next-run times
journalctl --user -u ai-chatbot-backup  # View one job's logs
```

Service units run oneshot scripts via the project virtualenv:

```ini
# systemd/ai-chatbot-<job>.service
[Service]
Type=oneshot
ExecStart=%h/src/ai-chatbot/.venv/bin/python scripts/<script>.py
```

Timers use `OnCalendar` for the schedule, `Persistent=true` for downtime catch-up, and
usually `RandomizedDelaySec` to avoid a thundering herd at the top of the hour.

## Development: `dev_scheduler`

In development there is no systemd. A single background loop in
[`src/agent/dev_scheduler.py`](../../src/agent/dev_scheduler.py) provides parity.

- Started from `create_app()` **only when** `Config.is_development()` is true (see
  [`src/app.py`](../../src/app.py)).
- Runs as a `daemon=True` thread that dies with the main process.
- Wakes every `SCHEDULER_INTERVAL_SECONDS` (60s) and, on each tick, runs the
  due-checks for the jobs that need dev parity.
- Idempotent per-day jobs use a **kv-store last-run stamp** (`run_*_if_due()`) so the
  60-second tick triggers each daily job at most once per day.

```python
# src/agent/dev_scheduler.py (loop body, abridged)
while not stop_event.is_set():
    run_scheduled_agents()          # dev stand-in for the agent-scheduler timer
    run_file_cleanup_if_due()       # dev stand-in for the file-cleanup timer
    stop_event.wait(SCHEDULER_INTERVAL_SECONDS)
```

Note: not every production timer has a dev-loop entry. The `dev_scheduler` mirrors only
the jobs that matter during local development (currently the agent scheduler and file
cleanup). Backup, vacuum, currency, and memory-defrag run only from timers in production.

## Adding a New Scheduled Job

1. **Write a runnable script** in [`scripts/`](../../scripts/) (e.g. `scripts/my_job.py`)
   with a `main()` entry point. If it is a daily/idempotent job, guard the work with a
   kv-store last-run stamp so it can be safely re-invoked.
2. **Add a systemd pair** in [`systemd/`](../../systemd/):
   - `ai-chatbot-my-job.service` — `Type=oneshot`, `ExecStart=` the script via the venv.
   - `ai-chatbot-my-job.timer` — `OnCalendar=` the schedule, `Persistent=true`, and a
     `RandomizedDelaySec` if it runs at a fixed time.
3. **Wire it into `make deploy`** — copy the `.service`/`.timer`, then `enable` and
   `start` the timer (follow the existing entries in the [`Makefile`](../../Makefile)).
4. **Add dev parity (if needed)** — if the job should also run in local development, add a
   `run_my_job_if_due()` call to the `dev_scheduler` loop.
5. **(Optional) Manual target** — add a `make my-job` target that runs the script directly
   for on-demand execution.

## Current Scheduled Jobs

All units live in [`systemd/`](../../systemd/) with the `ai-chatbot-<name>` prefix. Times
are the configured `OnCalendar` value (before any `RandomizedDelaySec`).

| Job | Schedule | Script | Dev parity |
|-----|----------|--------|------------|
| Agent scheduler | Every minute (`*:*:00`, `OnBootSec=30`) | [`run_agent_scheduler.py`](../../scripts/run_agent_scheduler.py) | Yes — `run_scheduled_agents()` |
| Database backup | Daily 02:00 (+30m jitter) | [`backup_databases.py`](../../scripts/backup_databases.py) | No |
| File cleanup | Daily 02:30 | [`cleanup_files.py`](../../scripts/cleanup_files.py) | Yes — `run_file_cleanup_if_due()` |
| Database vacuum | Weekly Sun 03:00 (+1h jitter) | [`vacuum_databases.py`](../../scripts/vacuum_databases.py) | No |
| Memory defrag | Daily 03:30 (+30m jitter) | [`defragment_memories.py`](../../scripts/defragment_memories.py) | No |
| Currency rates | Daily 04:00 (+30m jitter) | [`update_currency_rates.py`](../../scripts/update_currency_rates.py) | No |

Several jobs also have manual Make targets for on-demand runs: `make backup`,
`make vacuum`, `make update-currency`, `make defrag-memories`.

## Key Files

- [dev_scheduler.py](../../src/agent/dev_scheduler.py) - Development background loop
- [app.py](../../src/app.py) - Starts the dev scheduler in development mode only
- [scheduler.py](../../src/agent/scheduler.py) - Shared agent-scheduling logic (used by both timer and dev loop)
- [file_retention.py](../../src/utils/file_retention.py) - `run_file_cleanup_if_due()` kv-stamp throttle
- [systemd/](../../systemd/) - `.service` / `.timer` unit files
- [scripts/](../../scripts/) - Runnable job scripts
- [Makefile](../../Makefile) - `deploy` target installs/enables timers; manual job targets

## See Also

- [Database](database.md) - Backup and vacuum job details
- [Agents](../features/agents.md) - Autonomous agents driven by the agent scheduler
- [Cost Tracking](../features/cost-tracking.md) - Currency rates job feeds cost conversion
- [Memory and Context](../features/memory-and-context.md) - Memory defragmentation job
