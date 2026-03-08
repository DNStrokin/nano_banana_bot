import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../bot')))

from navigation import (
    NAVIGATION_GRAPH,
    ROUTE_MAIN,
    ROUTE_PROFILE,
    ROUTE_SHOP,
    ROUTE_TARIFFS,
    validate_navigation_graph,
)
from navigation import resolve_profile_navigation


class TestNavigationGraph(unittest.TestCase):
    def _walk(self, start: str, actions: list[str]) -> str:
        node = start
        for action in actions:
            self.assertIn(node, NAVIGATION_GRAPH, f"Unknown route: {node}")
            self.assertIn(action, NAVIGATION_GRAPH[node], f"Action '{action}' missing for route '{node}'")
            node = NAVIGATION_GRAPH[node][action]
        return node

    def test_graph_has_no_dead_ends_or_unreachable_routes(self):
        dead_ends, unreachable = validate_navigation_graph()
        self.assertEqual(dead_ends, [])
        self.assertEqual(unreachable, [])

    def test_e2e_start_to_creation_cancel_back_to_main(self):
        end = self._walk(
            ROUTE_MAIN,
            ["open_workshop", "select_model", "cancel", "to_main"],
        )
        self.assertEqual(end, ROUTE_MAIN)

    def test_e2e_profile_to_buy_and_upgrade_paths(self):
        # main -> profile -> shop -> cancel -> main
        end_shop = self._walk(
            ROUTE_MAIN,
            ["open_profile", "buy", "cancel", "to_main"],
        )
        self.assertEqual(end_shop, ROUTE_MAIN)

        # main -> profile -> tariffs -> cancel -> main
        end_tariffs = self._walk(
            ROUTE_MAIN,
            ["open_profile", "upgrade", "cancel", "to_main"],
        )
        self.assertEqual(end_tariffs, ROUTE_MAIN)

    def test_profile_navigation_router_mapping(self):
        self.assertEqual(resolve_profile_navigation("buy"), ROUTE_SHOP)
        self.assertEqual(resolve_profile_navigation("upgrade"), ROUTE_TARIFFS)
        self.assertEqual(resolve_profile_navigation("unknown"), ROUTE_PROFILE)


if __name__ == '__main__':
    unittest.main()
