from django import template

register = template.Library()

_BADGES = {
    "active": "ok", "approved": "ok", "low": "ok", "success": "ok",
    "pending": "warn", "suspended": "warn", "medium": "warn", "manager": "warn",
    "terminated": "bad", "rejected": "bad", "high": "bad", "cancelled": "muted", "skipped": "muted",
}


@register.filter
def badge(value):
    return _BADGES.get(str(value).lower(), "muted")


@register.filter
def initials(user):
    parts = (getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "?")).split()
    return "".join(p[0] for p in parts[:2]).upper() or "?"


@register.filter
def short_ua(ua):
    ua = ua or ""
    for needle, name in (("Edg/", "Edge"), ("Chrome/", "Chrome"), ("Firefox/", "Firefox"), ("Safari/", "Safari")):
        if needle in ua:
            return name
    return "Browser"
