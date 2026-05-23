"""FastAPI routers that consume the composition :class:`Container`.

Routers pull singletons (use case, repository, event bus, upstream HTTP
client) off ``request.app.state.container`` and never re-wire dependencies
themselves.
"""
