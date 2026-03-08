"""Navigation routes and graph helpers for user-facing flows."""

from __future__ import annotations

from collections import deque

# Nodes
ROUTE_MAIN = "main"
ROUTE_WORKSHOP = "workshop"
ROUTE_CREATION_CONFIG = "creation_config"
ROUTE_PROFILE = "profile"
ROUTE_SHOP = "shop"
ROUTE_TARIFFS = "tariffs"
ROUTE_CANCELLED = "cancelled"

# Terminal states that are intentionally final for user navigation.
TERMINAL_ROUTES = {ROUTE_MAIN, ROUTE_CANCELLED}

# Explicit state graph for primary user paths.
NAVIGATION_GRAPH: dict[str, dict[str, str]] = {
    ROUTE_MAIN: {
        "open_workshop": ROUTE_WORKSHOP,
        "open_profile": ROUTE_PROFILE,
        "open_tariffs": ROUTE_TARIFFS,
    },
    ROUTE_WORKSHOP: {
        "select_model": ROUTE_CREATION_CONFIG,
        "back_main": ROUTE_MAIN,
        "cancel": ROUTE_CANCELLED,
    },
    ROUTE_CREATION_CONFIG: {
        "submit_prompt": ROUTE_WORKSHOP,
        "back_main": ROUTE_MAIN,
        "cancel": ROUTE_CANCELLED,
    },
    ROUTE_PROFILE: {
        "buy": ROUTE_SHOP,
        "upgrade": ROUTE_TARIFFS,
        "back_main": ROUTE_MAIN,
    },
    ROUTE_SHOP: {
        "cancel": ROUTE_CANCELLED,
        "back_main": ROUTE_MAIN,
    },
    ROUTE_TARIFFS: {
        "cancel": ROUTE_CANCELLED,
        "back_main": ROUTE_MAIN,
    },
    ROUTE_CANCELLED: {
        "to_main": ROUTE_MAIN,
    },
}


def validate_navigation_graph(
    graph: dict[str, dict[str, str]] = NAVIGATION_GRAPH,
    start_route: str = ROUTE_MAIN,
    terminal_routes: set[str] = TERMINAL_ROUTES,
) -> tuple[list[str], list[str]]:
    """Returns (dead_ends, unreachable) for CI checks."""
    dead_ends: list[str] = []
    for route, transitions in graph.items():
        if route in terminal_routes:
            continue
        if not transitions:
            dead_ends.append(route)

    visited: set[str] = set()
    queue: deque[str] = deque([start_route])
    while queue:
        node = queue.popleft()
        if node in visited or node not in graph:
            continue
        visited.add(node)
        queue.extend(graph[node].values())

    unreachable = sorted(set(graph.keys()) - visited)
    return sorted(dead_ends), unreachable


def resolve_profile_navigation(action: str) -> str:
    routes = {
        "buy": ROUTE_SHOP,
        "upgrade": ROUTE_TARIFFS,
    }
    return routes.get(action, ROUTE_PROFILE)
