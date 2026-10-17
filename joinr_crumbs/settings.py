from joinr.settings import TEMPLATES

TEMPLATES[0]["OPTIONS"]["context_processors"].append(
    "joinr_crumbs.context_processors.breadcrumbs",
)
