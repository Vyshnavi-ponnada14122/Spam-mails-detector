from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from email_service import scan_all_accounts

scheduler = BackgroundScheduler()


def start_scheduler():
    if scheduler.state != 1:
        scheduler.add_job(
            scan_all_accounts,
            trigger=IntervalTrigger(minutes=5),
            next_run_time=datetime.utcnow() + timedelta(seconds=5),
            id="email_scanner",
            replace_existing=True,
        )
        scheduler.start()
