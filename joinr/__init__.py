"""
init.py
"""

import sys

# Patch makemigrations and migrate to use JoinrAutodetector.
#
# Django stores the autodetector as a class attribute on each command
# (`autodetector = MigrationAutodetector`), so we patch the class attribute
# directly — patching the module-level name has no effect.
#
# Django 6.x requires both commands to share the same autodetector class
# (system check commands.E001), so we always patch both.
try:
    from django.core.management.commands.makemigrations import Command as _MM
    from django.core.management.commands.migrate import Command as _Migrate

    from joinr.inherit.autodetect import JoinrAutodetector

    _MM.autodetector = JoinrAutodetector
    _Migrate.autodetector = JoinrAutodetector
except ImportError:
    pass

from joinr.__version__ import __version__  # noqa: E402,F401
