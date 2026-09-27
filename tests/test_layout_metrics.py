"""Bounded automatic resizing must settle without hiding a failing geometry loop."""
import unittest
from merlin_ui.layout_metrics import AutomaticSizeGuard


class AutomaticSizeGuardTests(unittest.TestCase):
    def test_alternating_minimum_latches_until_context_changes(self):
        guard=AutomaticSizeGuard();context=(1120,1.5)
        for size in (650,800,650):self.assertTrue(guard.allow(context,(900,size),now=0))
        self.assertFalse(guard.allow(context,(900,800),now=.1))
        self.assertFalse(guard.allow(context,(900,650),now=100))
        self.assertTrue(guard.allow((1200,1.5),(900,650),now=100))
        self.assertFalse(guard.blocked)

    def test_runaway_growth_is_bounded_and_normal_edits_are_allowed(self):
        guard=AutomaticSizeGuard(maximum_changes=4)
        for size in (650,660,670,680):self.assertTrue(guard.allow((1,),(900,size),now=0))
        self.assertFalse(guard.allow((1,),(900,690),now=.1))
        guard=AutomaticSizeGuard(maximum_changes=4)
        for index in range(30):self.assertTrue(guard.allow((1,),(900,650+index),now=index*3))

    def test_identical_proposals_do_not_exhaust_guard(self):
        guard=AutomaticSizeGuard()
        for _ in range(100):self.assertTrue(guard.allow((1,),(900,650),now=0))
        self.assertFalse(guard.blocked)
