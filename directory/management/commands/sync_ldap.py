from django.core.management.base import BaseCommand

from directory import sync


class Command(BaseCommand):
    help = "Import and reconcile directory users (new, moved, disabled)."

    def handle(self, *args, **opts):
        self.stdout.write(str(sync.sync_all()))
