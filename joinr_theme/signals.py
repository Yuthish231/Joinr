"""
Signals for the joinr_theme app
"""

# themes/signals.py
# Define your joinr_theme signals here
from django.db.models.signals import post_migrate
from django.db.utils import OperationalError, ProgrammingError
from django.dispatch import receiver

from .models import THEMES_DATA, JoinrColorTheme


@receiver(post_migrate)
def create_default_themes(sender, **kwargs):
    """
    Create default color joinr_theme after migration
    """
    # Only run for the joinr_theme app
    if sender.name != "joinr_theme":
        return

    # Check if joinr_theme already exist
    try:
        # Table may not exist yet in some migration orders
        if JoinrColorTheme.objects.exists():
            return
    except (OperationalError, ProgrammingError):
        # Table not created yet — skip silently
        return

    print("Creating default color themes...")
    created_count = 0

    for theme_data in THEMES_DATA:
        try:
            theme, created = JoinrColorTheme.objects.get_or_create(
                name=theme_data["name"], defaults=theme_data
            )
            if created:
                created_count += 1
                print(f"Created theme: {theme.name}")
            else:
                print(f"Theme already exists: {theme.name}")
        except Exception as e:
            print(f"Error creating theme {theme_data['name']}: {str(e)}")

    print(f"\nSuccessfully created {created_count} themes.")
