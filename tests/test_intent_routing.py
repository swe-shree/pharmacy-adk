import unittest

from app.fast_path import handle_fast_path
from app.intent_routing import select_fast_route


class IntentRoutingTests(unittest.TestCase):
    def test_select_fast_route_is_domain_based(self):
        cases = [
            ("What are the side effects of an unfamiliar medication?", None),
            ("Find general medicine safety information.", None),
            ("Show my rewards points.", None),
            ("Please check whether this item is in stock at a pharmacy.", ("commerce",)),
            ("I feel unwell and want to add the medicine to my cart.", ("commerce",)),
            ("Buy this newly released medicine.", ("commerce",)),
            ("Could you help me understand this?", None),
            ("Reschedule my doctor appointment.", None),
        ]
        for message, agents in cases:
            with self.subTest(message=message):
                result = select_fast_route(message)
                self.assertEqual(result.agents if result else None, agents)

    def test_product_names_do_not_participate_in_routing(self):
        result = select_fast_route("Find a product called entirely-new-name")
        self.assertIsNotNone(result)
        self.assertEqual(result.agents, ("commerce",))

    def test_only_emergency_guidance_uses_the_direct_fast_path(self):
        self.assertTrue(handle_fast_path("emergency info", "user_001")["handled"])
