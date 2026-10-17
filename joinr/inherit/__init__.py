"""
joinr/inherit/

Extension infrastructure for Joinr — model field injection and CBV replacement.

Key public symbols re-exported here for convenience:

    from joinr.inherit import JoinrViewInheritMixin   # view extension
    from joinr.inherit import JoinrModelBase           # model metaclass
    from joinr.inherit import INJECTION_MAP              # migration routing
    from joinr.inherit import VIEW_REGISTRY              # registered views
"""

from joinr.inherit.extension_registry import INJECTION_MAP
from joinr.inherit.model_inherit import EXTENSION_REGISTRY, JoinrModelBase
from joinr.inherit.view_inherit import JoinrViewInheritMixin
from joinr.inherit.view_registry import VIEW_REGISTRY

__all__ = [
    "JoinrViewInheritMixin",
    "JoinrModelBase",
    "INJECTION_MAP",
    "EXTENSION_REGISTRY",
    "VIEW_REGISTRY",
]
