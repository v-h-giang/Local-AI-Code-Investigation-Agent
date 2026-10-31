"""V5.11: Qwen interprets the question using local KB hints, no extra model call."""
from __future__ import annotations
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codebase import Repo
from code_intelligence import _plan_with_qwen, build_intelligence, investigate
from knowledge_base import build_knowledge
from semantic_knowledge import kb_prompt_context


class CaptureModel:
    def __init__(self, answer):
        self.answer=answer
        self.calls=[]
    def call(self, messages, tools=False, num_predict=None, **kwargs):
        self.calls.append({"messages":messages,"tools":tools,
                           "num_predict":num_predict})
        return {"content":self.answer}


class SemanticKnowledgePlannerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.project=self.root/"project"
        self.project.mkdir()
        (self.project/"module.f90").write_text(
            "module checkpoint_system\ncontains\n"
            "subroutine restart(state)\nend subroutine restart\n"
            "end module checkpoint_system\n",encoding="utf-8")
        self.repo=Repo(self.project)
        index=build_intelligence(self.repo,self.root/"out",verbose=False)
        self.assertTrue(Path(index["index"]).exists())
        self.db=self.root/"global.sqlite"
        env=patch.dict(os.environ,{"LOCAL_CODE_AGENT_KB_PATH":str(self.db)})
        env.start()
        self.addCleanup(env.stop)
        build_knowledge(db_path=self.db)

    def test_context_contains_relevant_concepts_and_repo_languages(self):
        context=kb_prompt_context(
            "How can workflow checkpoint resume after interruption?",
            repo=self.repo,max_chars=2300)
        self.assertIn("workflow.checkpoint",context)
        self.assertIn("Detected repository languages",context)
        self.assertIn("fortran=",context)
        self.assertLessEqual(len(context),2300)
        self.assertNotIn("source citations",context)

    def test_conceptual_question_without_keyword_uses_bounded_fallback(self):
        context=kb_prompt_context(
            "How does the system continue after a crash while preserving progress?",
            self.repo,max_chars=2300)
        self.assertIn("General programming concepts",context)
        self.assertLessEqual(len(context),2300)

    def test_one_existing_ai_call_receives_kb_context_and_normalizes_plan(self):
        answer=json.dumps({
            "intent":"trace","queries":["checkpoint resume","restore state"],
            "symbols":["restoreSession"],"graph_depth":2,
            "analysis_goals":["verify state restoration"]})
        model=CaptureModel(answer)
        plan=_plan_with_qwen(
            model,"How does the workflow resume after a checkpoint?",
            repo=self.repo)
        self.assertEqual(len(model.calls),1)
        self.assertEqual(plan["intent"],"trace")
        self.assertIn("restore state",plan["queries"])
        self.assertTrue(plan["knowledge_prompt_used"])
        prompt=model.calls[0]["messages"][1]["content"]
        self.assertIn("Knowledge Base context",prompt)
        self.assertIn("workflow.checkpoint",prompt)
        self.assertIn("fortran=",prompt)
        self.assertFalse(model.calls[0]["tools"])

    def test_model_cannot_add_paths_or_commands_to_planner_output(self):
        model=CaptureModel(json.dumps({
            "intent":"execute","queries":["restore state","; rm -rf /"],
            "symbols":["FakeClass","../outside"],"graph_depth":100,
            "analysis_goals":["find", "investigate"]}))
        plan=_plan_with_qwen(model,"Where is restore state?",repo=self.repo)
        self.assertEqual(plan["intent"],"locate")
        self.assertNotIn("; rm -rf /",plan["queries"])
        self.assertNotIn("../outside",plan["symbols"])
        self.assertEqual(plan["graph_depth"],3)
        self.assertEqual(len(model.calls),1)

    def test_no_kb_still_runs_existing_ai_planner_once(self):
        with patch.dict(os.environ,{"LOCAL_CODE_AGENT_KB_PATH":
                                    str(self.root/"missing.sqlite")}):
            model=CaptureModel('{"intent":"locate","queries":["solver"],'
                               '"symbols":[],"graph_depth":1}')
            plan=_plan_with_qwen(model,"Where is solver?",repo=self.repo)
            self.assertEqual(len(model.calls),1)
            self.assertTrue(plan["queries"])
            # Global KB can be absent while repo-language metadata remains
            # available as bounded, non-authoritative planning context.
            user_prompt=model.calls[0]["messages"][1]["content"]
            self.assertNotIn("General programming concepts",user_prompt)
            self.assertIn("Detected repository languages",user_prompt)
            self.assertTrue(plan["knowledge_prompt_used"])

    def test_qwen_plan_queries_add_secondary_file_candidates(self):
        from investigation_loop import investigate_iteratively
        model=CaptureModel('{"action":"finish"}')
        # Question and file do not share a term; the model's normalized
        # technical search query is what links them.
        result=investigate_iteratively(
            self.repo,"Where is the invisible staging sequence?",
            model,{"intent":"locate","queries":["restart"],
                   "symbols":[],"graph_depth":1,"analysis_goals":[]},
            max_steps=1,review_rounds=0,planner="qwen-json-plan")
        paths=[r["path"] for r in result["file_discovery"]["candidates"]]
        self.assertIn("module.f90",paths)
        self.assertGreaterEqual(
            result["file_discovery"].get("qwen_secondary_candidates",0),1)
        self.assertTrue(all(not item.get("citation",False)
                            for item in result["file_discovery"]["candidates"]))

    def test_lexical_fallback_does_not_trust_plan_for_extra_discovery(self):
        from investigation_loop import investigate_iteratively
        result=investigate_iteratively(
            self.repo,"Where is the invisible staging sequence?",
            CaptureModel('{"action":"finish"}'),
            {"intent":"locate","queries":["restart"],"symbols":[],
             "graph_depth":1,"analysis_goals":[]},
            max_steps=1,review_rounds=0,planner="lexical-fallback")
        self.assertEqual(
            result["file_discovery"].get("qwen_secondary_candidates",0),0)

    def test_without_model_never_calls_semantic_planner(self):
        with patch("code_intelligence._plan_with_qwen",
                   side_effect=AssertionError("model used")):
            result=investigate(self.repo,"Where is restart?",llm=None)
        self.assertIn("source_excerpts",result)
        self.assertEqual(result["retriever"],
                         "SQLite FTS5 lexical BM25; not embeddings")


if __name__=="__main__":
    unittest.main()
