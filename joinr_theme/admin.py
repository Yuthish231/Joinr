"""
Admin registration for the joinr_theme app
"""

from django.contrib import admin

from joinr_theme.models import CompanyTheme, JoinrColorTheme

# Register your joinr_theme models here.
admin.site.register(JoinrColorTheme)
admin.site.register(CompanyTheme)
