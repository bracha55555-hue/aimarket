"""Read-only aliases for public AI-agent discovery crawlers."""

ALIASES = {
    "/api/agents": (
        "/agents.json",
        "/.well-known/agents.json",
        "/agent-directory.json",
        "/.well-known/agent-directory.json",
    ),
    "/.well-known/mcp.json": ("/mcp.json",),
    "/mcp/server-card": ("/.well-known/mcp/server-card.json",),
    "/llms.txt": ("/agents.txt",),
}


def install_discovery_compat(app):
    """Expose existing handlers without changing their payload or write permissions."""
    routes = {getattr(route, "path", None): route for route in app.routes}
    for canonical, aliases in ALIASES.items():
        source = routes.get(canonical)
        if source is None or "GET" not in (getattr(source, "methods", set()) or set()):
            raise RuntimeError(f"Missing GET discovery route: {canonical}")
        for alias in aliases:
            if alias in routes:
                raise RuntimeError(f"Discovery alias conflicts with existing route: {alias}")
            app.add_api_route(alias, source.endpoint, methods=["GET"], include_in_schema=False)
            routes[alias] = app.routes[-1]
