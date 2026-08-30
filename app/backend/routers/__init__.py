"""API router package.

Routers are intentionally imported by the application factory only for the
runtime mode that needs them.  In particular, Demo mode must not import the
mail stack as a side effect of importing this package.
"""

__all__ = ["agent", "applications", "demo", "health", "mail"]
