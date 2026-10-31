"""Offline regression tests for universal source investigation knowledge (V5.4+)."""
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from architecture import _scan
from codebase import Repo
from code_intelligence import build_intelligence, symbol_query, search_file_candidates
from knowledge_base import (build_knowledge, query_knowledge, related_concepts, expand_query_terms,
                            knowledge_status)
from language_registry import language_for, is_source_file
from lsp_bridge import import_lsp_locations, lookup_lsp_locations
from repository_knowledge import technology_overview


class UniversalKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)
        self.root=self.home/"source"
        self.root.mkdir()
        self.kb=self.home/"knowledge"/"global.sqlite"
        patcher=patch.dict(os.environ,{"LOCAL_CODE_AGENT_KB_PATH":str(self.kb)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pack_is_versioned_repeatable_and_offline(self):
        first=build_knowledge(db_path=self.kb)
        self.assertIn("core-programming",first["updated_packs"])
        self.assertGreaterEqual(first["concepts"],126)
        second=build_knowledge(db_path=self.kb)
        self.assertEqual(second["updated_packs"],[])
        self.assertIn("core-programming",second["unchanged_packs"])
        status=knowledge_status(db_path=self.kb)
        self.assertEqual(status["packs"],6)
        hits=query_knowledge("How do I resume a workflow checkpoint?",
                             db_path=self.kb)
        self.assertIn("workflow.checkpoint",{h["concept_id"] for h in hits})
        self.assertTrue(all(h["citation"] is False for h in hits))
        links=related_concepts("workflow.checkpoint",db_path=self.kb)
        self.assertIn("workflow.persistence",{item["concept_id"] for item in links})
        self.assertTrue(all(item["citation"] is False for item in links))
        self.assertIn("checkpointing",expand_query_terms(
            "How to resume a workflow?",db_path=self.kb))

    def test_custom_pack_update_removes_obsolete_alias(self):
        directory=self.home/"custom"
        directory.mkdir()
        pack={
            "schema_version":1,"pack_id":"custom-domain",
            "version":"1.0","license":"CC0-1.0",
            "concepts":[{
                "id":"custom.worker","domain":"runtime","label":"worker pool",
                "description":"Worker pool concept, not evidence",
                "source":"local-test","aliases":["legacyworker","worker pool"]
            }],
            "relations":[]
        }
        packfile=directory/"custom.json"
        packfile.write_text(json.dumps(pack),encoding="utf-8")
        build_knowledge(db_path=self.kb,pack_dir=directory)
        self.assertTrue(query_knowledge("legacyworker",db_path=self.kb))
        pack["concepts"][0]["aliases"]=["modernworker","worker pool"]
        pack["version"]="1.1"
        packfile.write_text(json.dumps(pack),encoding="utf-8")
        build_knowledge(db_path=self.kb,pack_dir=directory)
        self.assertFalse(query_knowledge("legacyworker",db_path=self.kb))
        self.assertTrue(query_knowledge("modernworker",db_path=self.kb))

    def test_reject_invalid_pack_relations(self):
        directory=self.home/"invalid"
        directory.mkdir()
        invalid={"schema_version":1,"pack_id":"unsafe-pack","version":"1",
            "license":"CC0-1.0","concepts":[
                {"id":"valid.id","domain":"test","label":"testing",
                 "description":"test concept","source":"test",
                 "aliases":["testing"]}],
            "relations":[{"from":"valid.id","to":"other.id","kind":"related"}]}
        (directory/"bad.json").write_text(json.dumps(invalid),encoding="utf-8")
        with self.assertRaises(ValueError):
            build_knowledge(db_path=self.kb,pack_dir=directory)

    def test_multi_language_scanning_and_declaration_hints(self):
        sources={
            "compute.f90":"module grid\ncontains\nsubroutine advance(dt)\nend subroutine\nend module grid\n",
            "service.go":"package main\nfunc Serve() {}\n",
            "types.rs":"pub struct State {}\npub fn calculate(x:i32) -> i32 { x }\n",
            "core.cpp":"class Engine { };\n",
            "frontend.ts":"export function updateState() {}\n",
            "run.tf":"resource \"null_resource\" \"x\" {}\n",
        }
        for file,text in sources.items():
            (self.root/file).write_text(text,encoding="utf-8")
        self.assertEqual(language_for("compute.f90"),"fortran")
        self.assertEqual(language_for("service.go"),"go")
        self.assertTrue(is_source_file("Dockerfile"))
        self.assertEqual({name for name,_ in _scan(self.root)},set(sources))
        repo=Repo(self.root)
        self.assertEqual({s.path for s in repo.files(limit=40)},set(sources))
        self.assertIn("subroutine advance",repo.read_file("compute.f90",1,4))
        output=self.home/"out"
        result=build_intelligence(repo,output,verbose=False)
        self.assertEqual(result["changed_files"],len(sources))
        self.assertTrue(symbol_query(repo,"advance")["definitions"])
        self.assertTrue(symbol_query(repo,"Serve")["definitions"])
        self.assertTrue(symbol_query(repo,"calculate")["definitions"])
        with closing(sqlite3.connect(result["index"])) as conn:
            profiles=technology_overview(conn)
        languages={item["language"] for item in profiles}
        for language in ("fortran","go","rust","cpp","typescript"):
            self.assertIn(language,languages)
        self.assertEqual(build_intelligence(repo,output,verbose=False)["changed_files"],0)

    def test_retrieval_knowledge_cannot_create_source_citations(self):
        (self.root/"checkpoint_handler.go").write_text(
            "package x\nfunc checkpoint() {}\n",encoding="utf-8")
        repo=Repo(self.root)
        build_intelligence(repo,self.home/"out",verbose=False)
        ranked=search_file_candidates(repo,
            "How should a workflow resume after interruption?",limit=8)
        self.assertTrue(ranked)
        self.assertTrue(all(row["citation"] is False for row in ranked))
        self.assertTrue(all("line" not in row for row in ranked))

    def test_safe_lsp_import_only_accepts_source_within_repo(self):
        inside=self.root/"file.go"
        inside.write_text("package main\nfunc Start() {}\n",encoding="utf-8")
        outside=self.home/"secret.go"
        outside.write_text("secret\n",encoding="utf-8")
        repo=Repo(self.root)
        build_intelligence(repo,self.home/"out",verbose=False)
        export=self.home/"lsp.json"
        data=[
            {"symbol":"Start","uri":inside.as_uri(),
             "range":{"start":{"line":1,"character":5}}},
            {"symbol":"Secret","uri":outside.as_uri(),
             "range":{"start":{"line":0,"character":0}}},
            {"symbol":"OutOfRange","uri":inside.as_uri(),
             "range":{"start":{"line":999,"character":0}}},
        ]
        export.write_text(json.dumps(data),encoding="utf-8")
        result=import_lsp_locations(repo,export)
        self.assertEqual(result["imported"],1)
        self.assertEqual(result["rejected"],2)
        hits=lookup_lsp_locations(repo,"Start")
        self.assertEqual(len(hits),1)
        self.assertEqual(hits[0]["line"],2)
        self.assertFalse(hits[0]["citation"])
        self.assertFalse(lookup_lsp_locations(repo,"Secret"))


if __name__=="__main__":
    unittest.main()
