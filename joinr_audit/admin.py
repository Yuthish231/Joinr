"""
admin.py
"""

from django.contrib import admin

from joinr_audit.models import AuditTag, JoinrAuditInfo, JoinrAuditLog

# Register your models here.

admin.site.register(AuditTag)
