"""
APScheduler: run fetcher twice daily — 00:00 (hardcoded for daily baseline) and one configurable hour.
Configurable hour from FETCH_HOUR_2 in data/netmon.conf (default 20).
"""
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from fetcher import run_fetch

_scheduler = None


def _job_midnight():
    run_fetch(is_midnight=True)


def _job_other():
    run_fetch(is_midnight=False)


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    reschedule()
    _scheduler.start()


def reschedule():
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.remove_all_jobs()
    # One fetch at 00:00 (daily baseline for daily usage calc), one at configurable hour
    _scheduler.add_job(_job_midnight, CronTrigger(hour=0, minute=0), id="fetch_midnight")
    h2 = int(os.environ.get("FETCH_HOUR_2") or "20")
    _scheduler.add_job(_job_other, CronTrigger(hour=h2, minute=0), id="fetch_2")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
