import unittest
from unittest.mock import patch

from engine import NeoDBEngine
from neoql.runtime import NeoQLSession
from neoql.selection import Selection


class AppendixAConformanceTests(unittest.TestCase):
    def test_complete_example_is_one_lazy_composable_plan(self):
        engine = NeoDBEngine()
        session = NeoQLSession(engine)
        session.execute("create dataset users(graph{})")
        session.execute(
            'add {id=1, department="Engineering", performance=5.0, '
            'status="Employee", name="Ada", manager={name="Lin"}, deadline=""}, '
            '{id=2, department="Project", performance=4.8, '
            'status="Candidate", name="Compiler", manager={name="Mira"}, '
            'deadline="2026-09-01"}, '
            '{id=3, department="Project", performance=4.9, '
            'status="Active", name="NeoDB", manager={name="Grace", id=9}, '
            'deadline="2026-12-01"} into users'
        )
        session.execute("add link(label=works_on) between users({id=1}), users({id=2})")
        session.execute("add link(label=project) between users({id=2}), users({id=3})")

        dataset = engine.datasets["users"]
        with patch.object(
            dataset,
            "_selection_records",
            wraps=dataset._selection_records,
        ) as scan:
            session.execute(
                'employees = users({department="Engineering"}).'
                "traverse(works_on(), depth=1)"
            )
            session.execute("highPerformers = employees({performance>=4.5})")
            session.execute("projects = highPerformers.traverse(project())")
            session.execute(
                'activeProjects = projects({status="Active"}).'
                "(name, manager(name), deadline)"
            )
            active_projects = session.execute("activeProjects")

            self.assertIsInstance(active_projects, Selection)
            scan.assert_not_called()
            self.assertEqual(
                [node["node"] for node in active_projects.explain()["logical"]],
                [
                    "FilterPlan",
                    "TraversalPlan",
                    "FilterPlan",
                    "TraversalPlan",
                    "FilterPlan",
                    "ProjectionPlan",
                ],
            )
            scan.assert_not_called()

            self.assertEqual(
                active_projects.consume(),
                [
                    {
                        "name": "NeoDB",
                        "manager": {"name": "Grace"},
                        "deadline": "2026-12-01",
                    }
                ],
            )
            scan.assert_called_once()


if __name__ == "__main__":
    unittest.main()
