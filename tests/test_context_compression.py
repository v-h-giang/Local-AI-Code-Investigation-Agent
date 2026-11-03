"""Offline tests for switchable evidence compression; no Ollama required."""
from __future__ import annotations
import json
import unittest

from context_compression import compress, compress_c2, compress_c3, compress_c4


LINES=[
    (1,"1 | module checkpoint"),
    (2,"2 | implicit none"),
    (3,"3 | contains"),
    (4,"4 | subroutine restore_checkpoint()"),
    (5,"5 | if (restart_enabled) then"),
    (6,"6 | call restore_state()"),
    (7,"7 | endif"),
    (8,"8 | end subroutine restore_checkpoint"),
    (9,"9 | end module checkpoint"),
]


class FakeLLM:
    def __init__(self, content):
        self.content=content
        self.calls=0
    def call(self,messages,**kwargs):
        self.calls+=1
        return {"content":self.content}


class CompressionModesTests(unittest.TestCase):
    def check_evidence(self, excerpt, budget=780):
        self.assertIsNotNone(excerpt)
        self.assertLessEqual(len(json.dumps(excerpt,ensure_ascii=False)),budget)
        original={n:raw for n,raw in LINES}
        observed=[]
        for line in excerpt["content"].splitlines():
            prefix=line.split(" | ",1)[0]
            n=int(prefix)
            self.assertEqual(line,original[n])
            observed.append(f"restore.f90:{n}")
        self.assertEqual(observed,excerpt["source_refs"])
        self.assertEqual(observed,excerpt["visible_refs"])

    def test_c2_structure_mmr_retains_exact_source(self):
        result=compress_c2("restore.f90",LINES,"where is restore checkpoint",780)
        self.check_evidence(result)
        self.assertIn("restore_checkpoint",result["content"])

    def test_c3_selects_only_valid_source_ids(self):
        llm=FakeLLM('{"ids":[6,999,4,6]}')
        result=compress_c3("restore.f90",LINES,"restore checkpoint",780,llm)
        self.check_evidence(result)
        self.assertIn("6 | call restore_state()",result["content"])
        self.assertNotIn("999",str(result))
        self.assertEqual(llm.calls,1)

    def test_c3_malformed_model_response_falls_back_to_c2(self):
        expected=compress_c2("restore.f90",LINES,"restore checkpoint",780)
        result=compress_c3("restore.f90",LINES,"restore checkpoint",780,
                           FakeLLM("not a JSON object"))
        self.assertEqual(result,expected)

    def test_c4_summary_is_not_evidence(self):
        llm=FakeLLM('{"summary":"Calls restore_state for checkpoint.",'
                    '"ids":["restore.f90:6"]}')
        result=compress_c4("restore.f90",LINES,"restore checkpoint",780,llm)
        self.check_evidence(result)
        self.assertNotIn("semantic_note_unverified",result["source_refs"])
        self.assertTrue(set(result["source_refs"]).issubset({
            "restore.f90:"+str(n) for n,_ in LINES}))

    def test_c4_rejects_invalid_summary_citations(self):
        expected=compress_c2("restore.f90",LINES,"restore checkpoint",780)
        result=compress_c4("restore.f90",LINES,"restore checkpoint",780,
                           FakeLLM('{"summary":"Invented","ids":["other.f90:999"]}'))
        self.assertEqual(result,expected)

    def test_descriptive_modes_are_equivalent_to_older_aliases(self):
        for name, old_name in (
                ("structure_mmr","c2"),
                ("llm_evidence_select","c3"),
                ("structure_llm_summary","c4")):
            result=compress("restore.f90",LINES,"restore checkpoint",mode=name)
            self.check_evidence(result)
            self.assertEqual(result,compress("restore.f90",LINES,
                                             "restore checkpoint",mode=old_name))

    def test_default_and_legacy_modes_are_available(self):
        self.assertEqual(compress("restore.f90",LINES,"restore checkpoint"),
                         compress_c2("restore.f90",LINES,"restore checkpoint"))
        self.check_evidence(compress("restore.f90",LINES,
                                    "restore checkpoint",mode="legacy"))
        with self.assertRaises(ValueError):
            compress("restore.f90",LINES,"restore",mode="unknown")


if __name__=="__main__":
    unittest.main()
