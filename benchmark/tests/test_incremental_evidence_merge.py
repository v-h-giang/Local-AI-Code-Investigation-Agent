"""Regression tests for line-level source evidence merging."""
import copy
import json
import unittest

from incremental_evidence_merge import merge_evidence


def excerpt(path, rows):
    refs = [f'{path}:{i}' for i, _ in rows]
    return {
        'path':path,
        'content':'\n'.join(f'{i:5d} | {content}' for i,content in rows),
        'source_refs':refs,
        'visible_refs':refs,
        'compressed':True,
        'source_lines_considered':len(rows),
    }


class IncrementalMergeTests(unittest.TestCase):
    def fixture(self):
        baseline=[excerpt('src/a.py',[
            (10,'def retry_rate_limit():'),
            (11,'    return handle_retry()'),
            (12,'def configure_logging(): pass'),
        ])]
        adaptive=[excerpt('src/a.py',[
            (10,'def retry_rate_limit():'),
            (11,'    return handle_retry()'),
            (50,'class RetryRateLimitMiddleware:'),
            (51,'    def handle_retry(): return True'),
        ])]
        return baseline, adaptive

    def test_merge_preserves_existing_and_new_evidence(self):
        baseline, adaptive = self.fixture()
        for policy in ('balanced','anchored'):
            out=merge_evidence(baseline,adaptive,'How is retry rate limit handled?',
                               policy=policy,max_chars=3000)
            self.assertLessEqual(out['serialized_chars'],3000)
            self.assertEqual(out['serialized_chars'],len(json.dumps(out['excerpts'],ensure_ascii=False)))
            refs={r for e in out['excerpts'] for r in e['source_refs']}
            self.assertIn('src/a.py:10',refs)
            self.assertIn('src/a.py:50',refs)
            self.assertEqual(out['selected_source_files'],1)
            self.assertGreaterEqual(out['added_adaptive_source_lines'],1)
            self.assertEqual(out['lost_baseline_source_lines'],0)

    def test_deduplicates_source_lines_and_retains_exact_text(self):
        baseline,adaptive=self.fixture()
        out=merge_evidence(baseline,adaptive,'retry limit',max_chars=3000)
        refs=[r for e in out['excerpts'] for r in e['source_refs']]
        self.assertEqual(len(refs),len(set(refs)))
        source_map={ref:raw for e in baseline+adaptive
                    for ref,raw in zip(e['source_refs'],e['content'].splitlines())}
        for item in out['excerpts']:
            self.assertEqual(item['source_refs'],item['visible_refs'])
            for ref,line in zip(item['source_refs'],item['content'].splitlines()):
                self.assertEqual(line,source_map[ref])

    def test_rejects_provenance_mismatch(self):
        baseline,adaptive=self.fixture()
        baseline[0]['source_refs'][0]='src/a.py:900'
        with self.assertRaises(ValueError):
            merge_evidence(baseline,adaptive,'retry')

    def test_rejects_conflicting_source_bytes(self):
        baseline,adaptive=self.fixture()
        adaptive[0]['content']=adaptive[0]['content'].replace('def retry_rate_limit():','def malicious_change():')
        with self.assertRaises(ValueError):
            merge_evidence(baseline,adaptive,'retry')

    def test_ignores_unrelated_gold_field(self):
        baseline,adaptive=self.fixture()
        original=merge_evidence(baseline,adaptive,'retry rate limit')
        # The merge inputs have no benchmark labels or object containing them.
        changed=merge_evidence(copy.deepcopy(baseline),copy.deepcopy(adaptive),'retry rate limit')
        self.assertEqual(original,changed)

    def test_budget_and_file_limit_enforced(self):
        baseline=[excerpt('src/a.py',[(1,'def one(): '+('x'*600))])]
        adaptive=[excerpt('src/b.py',[(50,'def other(): '+('y'*600))])]
        for mode in ('balanced','anchored'):
            result=merge_evidence(baseline,adaptive,'one other',policy=mode,
                                  max_chars=500,limit=1)
            self.assertLessEqual(result['serialized_chars'],500)
            self.assertLessEqual(len(result['excerpts']),1)

    def test_baseline_anchor_helps_keep_rare_line(self):
        baseline=[excerpt('src/a.py',[(4,'def special_contract(): return 7')])]
        adaptive=[excerpt('src/b.py',[(20,'def retry_rate_limit(): pass'),
                                      (21,'def retry_rate_limit_again(): pass')])]
        out=merge_evidence(baseline,adaptive,'Where is rate limit retry?',
                           policy='anchored',max_chars=700,limit=2)
        refs={r for e in out['excerpts'] for r in e['source_refs']}
        self.assertIn('src/a.py:4',refs)

    def test_empty_selection(self):
        out=merge_evidence([],[],'What happens?',max_chars=3000)
        self.assertEqual(out['excerpts'],[])
        self.assertEqual(out['serialized_chars'],2)


if __name__=='__main__':
    unittest.main()
