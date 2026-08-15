import unittest
from axon.actions import ActionResult
from axon.core import Agent, EventBus, Planner, PlanStep
from axon.security import PermissionManager, Risk
from axon.tools import ToolRegistry, ToolSpec
from axon.planning import DailyPlanner, Task

class V15CoreTests(unittest.TestCase):
    def test_planner_orders_dependencies_and_detects_cycles(self):
        planner = Planner()
        steps = [PlanStep("b", "B", depends_on=["a"]), PlanStep("a", "A")]
        self.assertEqual([s.id for s in planner.build(steps)], ["a", "b"])
        with self.assertRaises(ValueError):
            planner.build([PlanStep("a", "A", depends_on=["b"]), PlanStep("b", "B", depends_on=["a"])])

    def test_registry_requires_confirmation_for_medium_risk(self):
        registry = ToolRegistry(PermissionManager())
        registry.register(ToolSpec("demo", "demo", lambda **_: ActionResult.success("ok"), Risk.MEDIUM, True))
        self.assertFalse(registry.execute("demo").ok)
        self.assertTrue(registry.execute("demo", confirmed=True).ok)

    def test_event_bus_observer_cannot_break_publish(self):
        bus = EventBus()
        seen = []
        bus.subscribe("x", lambda event: seen.append(event.data["value"]))
        bus.subscribe("x", lambda event: (_ for _ in ()).throw(RuntimeError("observer")))
        bus.publish("x", value=3)
        self.assertEqual(seen, [3])

    def test_daily_planner_prioritizes_tasks(self):
        plan = DailyPlanner().build([Task("low", 1), Task("high", 5)])
        self.assertEqual(plan.ordered_tasks()[0].title, "high")

if __name__ == "__main__":
    unittest.main()
