"""
Blueprints for API routes.
"""
from . import root, enrollment, identifier_sets, scan

routers = [
    root,
    enrollment,
    identifier_sets,
    scan,
]

blueprints = [ router.blueprint for router in routers ] # type: ignore
