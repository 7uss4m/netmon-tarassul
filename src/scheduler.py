"""
APScheduler BackgroundScheduler: run fetcher twice daily at configurable hours.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import db
from fetcher import run_fetch

_scheduler = None


def _job():
    run_fetch()


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
    h1 = int(db.get_setting("fetch_hour_1", "8") or "8")
    h2 = int(db.get_setting("fetch_hour_2", "20") or "20")
    _scheduler.add_job(_job, CronTrigger(hour=h1, minute=0), id="fetch_1")
    _scheduler.add_job(_job, CronTrigger(hour=h2, minute=0), id="fetch_2")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
