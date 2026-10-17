"""
joinr_automations/filters.py
"""

from joinr.filters import JoinrFilterSet, django_filters
from joinr_automations.models import MailAutomation


class AutomationFilter(JoinrFilterSet):
    """
    AutomationFilter
    """

    search = django_filters.CharFilter(field_name="title", lookup_expr="icontains")

    class Meta:
        model = MailAutomation
        fields = "__all__"
