"""
Custom Extension Loader for Hermes WebUI
Auto-discovers and registers all custom GET/POST routes.
Add new features by creating custom/<feature>/routes.py
"""

# List of all custom route modules
CUSTOM_ROUTE_MODULES = [
    "custom.email.routes",
]


def handle_custom_get(parsed, handler, j, bad) -> bool:
    """Try all custom GET handlers. Returns True if handled."""
    for module_path in CUSTOM_ROUTE_MODULES:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            if hasattr(mod, "register_get"):
                result = mod.register_get(parsed, handler, j, bad)
                if result:
                    return True
        except Exception:
            pass
    return False


def handle_custom_post(parsed, handler, body, j, bad) -> bool:
    """Try all custom POST handlers. Returns True if handled."""
    for module_path in CUSTOM_ROUTE_MODULES:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            if hasattr(mod, "register_post"):
                result = mod.register_post(parsed, handler, body, j, bad)
                if result:
                    return True
        except Exception:
            pass
    return False
