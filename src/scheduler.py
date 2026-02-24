import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from fetcher import run_fetch

_scheduler = None


def _job_baseline():
    run_fetch(is_baseline=True)


def _job_scheduled():
    run_fetch(is_baseline=False)


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    reschedule()
    _scheduler.start()


def _schedule_enabled() -> bool:
    v = (os.environ.get("ENABLE_SCHEDULE") or "true").strip().lower()
    return v in ("true", "1", "yes")


def reschedule():
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.remove_all_jobs()
    if not _schedule_enabled():
        return
    _scheduler.add_job(_job_baseline, CronTrigger(hour=1, minute=0), id="fetch_baseline")
    h2 = int(os.environ.get("FETCH_HOUR_2") or "20")
    _scheduler.add_job(_job_scheduled, CronTrigger(hour=h2, minute=0), id="fetch_scheduled")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
