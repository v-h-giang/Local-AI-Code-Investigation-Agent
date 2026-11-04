"""Offline smoke/regression tests for experimental memory, claims and symbols."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

from agent_context_memory import compact_history, prompt_history
from claim_verification import audit_claims
from semantic_retrieval import symbol_candidates, hybrid_search
from unittest.mock import patch


class AgentImprovementTests(unittest.TestCase):
    def test_compaction_is_bounded_and_does_not_mutate_trace(self):
        history=[{'step':i,'tool':'read_source','query':f'call_{i}',
                  'observation':{'content':f'{i} | source ' + ('x'*400)},
                  'source_refs':[f'code.f90:{i}']} for i in range(1,9)]
        snapshot=json.dumps(history)
        view,stats=compact_history(history,max_chars=1600,recent=2)
        self.assertLessEqual(len(json.dumps(view,ensure_ascii=False)),1600)
        self.assertGreater(stats['compacted_steps'],0)
        self.assertEqual(json.dumps(history),snapshot)
        self.assertTrue(all(r.get('source_refs',[]) for r in view))

    def test_disabled_memory_keeps_legacy_last_three(self):
        history=[{'step':n} for n in range(6)]
        view,_=prompt_history(history,enabled=False)
        self.assertEqual(view,history[-3:])

    def test_claim_citations_are_not_semantically_verified(self):
        answer=('Restoration calls a transaction handler code.f90:18.\n'
                'This is guaranteed at runtime code.f90:999.\n'
                'Another claim lacks source evidence.')
        report=audit_claims(answer,['code.f90:18'])
        self.assertEqual(report['invalid_citation_claims'],1)
        self.assertEqual(report['uncited_claims'],1)
        self.assertFalse(report['semantic_entailment_verified'])
        self.assertEqual(report['claims'][0]['status'],
                         'citation_present_not_semantically_verified')

    def test_claim_must_appear_in_numbered_source_observation(self):
        from claim_verification import audit_claims
        history=[{'observation':{'path':'code.f90',
                                'content':'18 | call restore_state()\\n19 | return'}}]
        report=audit_claims('The call occurs at code.f90:18.',
                            ['code.f90:18'],observations=history)
        self.assertEqual(report['claims'][0]['status'],
                         'citation_present_not_semantically_verified')
        missing=audit_claims('The call occurs at code.f90:999.',
                             ['code.f90:999'],observations=history)
        self.assertEqual(missing['claims'][0]['status'],
                         'citation_not_in_observed_source')

    def test_exact_symbol_search_only_returns_real_indexed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'code_intelligence.sqlite'
            with closing(sqlite3.connect(db)) as conn:
                with conn:
                    conn.execute('CREATE TABLE symbols (path TEXT,line INTEGER,'
                                 'end_line INTEGER,name TEXT,kind TEXT)')
                    conn.execute('INSERT INTO symbols VALUES (?,?,?,?,?)',
                                 ('code.f90',18,31,'restore_state','subroutine'))
            repo=SimpleNamespace(intelligence_db=db)
            result=symbol_candidates(repo,'Where is restore_state called?')
            self.assertEqual(result[0]['path'],'code.f90')
            self.assertEqual(result[0]['line_hint'],18)
            self.assertFalse(result[0]['citation'])
            self.assertEqual(symbol_candidates(repo,'unknown_method'),[])

    def test_hybrid_symbol_opt_in_preserves_base_search(self):
        repo=SimpleNamespace()
        def lexical(*args,**kwargs):return []
        def lines(*args,**kwargs):return []
        def dense(*args,**kwargs):return []
        symbol=lambda *args,**kwargs:[{'path':'code.f90','line_hint':18}]
        with patch('semantic_retrieval.dense_search',side_effect=dense):
            regular=hybrid_search(repo,'restore_state','unused',None,limit=8,
                                  lexical_search=lexical,source_search=lines)
            expanded=hybrid_search(repo,'restore_state','unused',None,limit=8,
                                   lexical_search=lexical,source_search=lines,
                                   include_symbols=True,symbol_search=symbol)
        self.assertEqual(regular,[])
        self.assertEqual(expanded[0]['path'],'code.f90')
        self.assertEqual(expanded[0]['line_hint'],18)


if __name__=='__main__':
    unittest.main()
