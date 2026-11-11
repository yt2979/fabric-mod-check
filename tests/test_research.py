import asyncio
import importlib.util
import json
import unittest
from types import SimpleNamespace


class ResearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(importlib.util.find_spec("research"), "Research workflow is required.")
        import research
        self.research = research

    async def test_ambiguous_question_only_asks_for_clarification(self):
        r = self.research
        calls = []

        async def model(agent, payload, **kwargs):
            calls.append(agent.name)
            return SimpleNamespace(final_output=r.Plan(kind="clarify", message="Which versions?", jobs=[], wants_changes=False, keep=[]))

        answer, trace = await r.investigate("Will it work?", runner=model)
        self.assertEqual(answer, "Which versions?")
        self.assertEqual(calls, ["Lead"])
        self.assertEqual(trace, [])

    async def test_no_mod_subject_cannot_dispatch_research_even_if_lead_guesses(self):
        r = self.research
        async def model(agent, payload, **kwargs):
            self.assertEqual(agent.name, "Lead")
            jobs = [r.Job(role=role, question="Guess", version_ids=["bAo1Qhte"])
                    for role in ("versions", "dependencies", "notes")]
            return SimpleNamespace(final_output=r.Plan(
                kind="research", message="", jobs=jobs, wants_changes=False, keep=[],
            ))

        answer, trace = await r.investigate("Will it work?", runner=model)
        self.assertIn("Which", answer)
        self.assertEqual(trace, [])

    async def test_parallel_research_and_targeted_follow_up_with_grounded_citations(self):
        r = self.research
        arrived = set()
        contexts = []
        gate = asyncio.Event()
        jobs = [
            r.Job(role=role, question=f"Investigate {role}", version_ids=["bAo1Qhte", "Z8VpxxGh"])
            for role in ("versions", "dependencies", "notes")
        ]

        async def model(agent, payload, context, max_turns):
            self.assertLessEqual(max_turns, 4)
            if agent.name == "Lead":
                return SimpleNamespace(final_output=r.Plan(kind="research", message="", jobs=jobs, wants_changes=True, keep=["iris"]))
            if agent.name == "Lead review":
                self.assertIn("Exact dependency evidence", payload)
                return SimpleNamespace(final_output=r.Review(jobs=[]))
            if agent.name == "Writer":
                return SimpleNamespace(final_output=r.Report(
                    headline="Conflicting Sodium pins",
                    findings=[r.Statement(text="The two required versions differ.", sources=["V-Z8VpxxGh", "V-bAo1Qhte"])],
                    limitations=["This is metadata evidence."],
                ))
            request = json.loads(payload)
            if agent.tools:
                self.assertEqual(max_turns, 1, "The evidence collection must have one bounded tool turn.")
                contexts.append(context)
                if request["round"] == 1:
                    arrived.add(agent.name)
                    if len(arrived) == 3:
                        gate.set()
                    await asyncio.wait_for(gate.wait(), timeout=1)
                output = context.use("check_pack", {"version_ids": ["bAo1Qhte", "Z8VpxxGh"]})
                self.assertIn('"status": "conflict"', output)
                if request["round"] == 2:
                    self.assertEqual(agent.name, "Dependency researcher")
                    self.assertEqual(request["keep"], ["iris"])
                    alternatives = context.use("find_alternatives", {
                        "version_ids": request["version_ids"], "keep": request["keep"],
                    })
                    self.assertIn("SMxNOGZ6", alternatives)
                return SimpleNamespace(final_output=output)
            self.assertIn("V-Z8VpxxGh", payload)
            return SimpleNamespace(final_output=r.Finding(
                summary="Exact dependency evidence",
                sources=["V-Z8VpxxGh", "V-bAo1Qhte"], gaps=["Check replacement notes"],
            ))

        answer, trace = await r.investigate("Compare those Iris and Indium versions", runner=model)
        self.assertEqual(len(arrived), 3)
        self.assertEqual(len({id(ctx) for ctx in contexts}), 4)
        self.assertEqual(len([t for t in trace if t["name"] == "check_pack"]), 4)
        self.assertTrue(all(t["agent"] for t in trace))
        self.assertTrue(any(t["name"] == "find_alternatives" and t["round"] == 2 for t in trace))
        self.assertIn("https://modrinth.com/mod/indium/version/Z8VpxxGh", answer)

    def test_citation_renderer_rejects_ids_not_seen_in_this_request(self):
        r = self.research
        report = r.Report(
            headline="Claim", findings=[r.Statement(text="Claim", sources=["V-Z8VpxxGh"])], limitations=[]
        )
        with self.assertRaisesRegex(ValueError, "Unverified citation"):
            r.render_report(report, set(), r.CATALOG)
