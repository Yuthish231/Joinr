import logging
import time

from django.core.management.base import BaseCommand

from lifecycle.services import run_due

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run lifecycle jobs (start dates, last working days, expiring grants). --once for a single pass."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=int, default=60)

    def handle(self, *args, **opts):
        while True:
            try:
                result = run_due()
                if any(result.values()):
                    self.stdout.write(f"scheduler: {result}")
            except Exception:  # noqa: BLE001 - keep the loop alive
                log.exception("scheduler pass failed")
            if opts["once"]:
                return
            time.sleep(opts["interval"])
