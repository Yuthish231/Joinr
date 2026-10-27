from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

GROUP_ADMIN = "IAM Admin"
GROUP_AUDITOR = "Auditor"


def _in_group(user, name):
    return user.is_authenticated and user.groups.filter(name=name).exists()


def is_iam_admin(user):
    return user.is_authenticated and (user.is_superuser or _in_group(user, GROUP_ADMIN))


def is_auditor(user):
    return is_iam_admin(user) or _in_group(user, GROUP_AUDITOR)


def is_manager(user):
    return user.is_authenticated and user.reports.exists()


def _guard(test, message):
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not test(request.user):
                messages.error(request, message)
                return redirect("dashboard")
            return view(request, *args, **kwargs)
        return wrapper
    return deco


iam_admin_required = _guard(is_iam_admin, "That area is for IAM administrators.")
auditor_required = _guard(is_auditor, "That area is for auditors and IAM administrators.")
