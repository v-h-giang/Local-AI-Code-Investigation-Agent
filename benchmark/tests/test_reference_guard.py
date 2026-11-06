"""Synthetic reference guard tests; independent of benchmark gold labels."""
import unittest
from reference_guard import choose_guarded


def excerpt(path, lines):
    refs=[f'{path}:{number}' for number,_ in lines]
    return {'path':path,'content':'\n'.join(f'{number:5d} | {text}'
                                               for number,text in lines),
            'source_refs':refs,'visible_refs':refs}


class ReferenceGuardTests(unittest.TestCase):
    def test_critical_missing_falls_back(self):
        baseline=[excerpt('src/a.py',[(10,'def retry_rate_limit(): pass')])]
        adaptive=[excerpt('src/b.py',[(20,'def configure(): pass')])]
        result=choose_guarded(baseline,adaptive,'Where is retry rate limit?')
        self.assertEqual(result['choice'],'baseline')
        self.assertEqual(result['critical_baseline_refs_missing_from_adaptive'],1)

    def test_preserved_critical_line_uses_adaptive(self):
        baseline=[excerpt('src/a.py',[(10,'def retry_rate_limit(): pass')])]
        adaptive=[excerpt('src/a.py',[(10,'def retry_rate_limit(): pass'),
                                      (11,'  return updated_policy')])]
        result=choose_guarded(baseline,adaptive,'Where is retry rate limit?')
        self.assertEqual(result['choice'],'adaptive_1')

    def test_query_guard_allows_more_query_terms(self):
        baseline=[excerpt('src/a.py',[(10,'def retry(): pass')])]
        adaptive=[excerpt('src/b.py',[(20,'def retry_rate_limit(): pass')])]
        result=choose_guarded(baseline,adaptive,'Where is retry rate limit?',
                              policy='query')
        self.assertEqual(result['choice'],'adaptive_1')

    def test_query_guard_rejects_no_query_gain(self):
        baseline=[excerpt('src/a.py',[(10,'def retry_rate_limit(): pass')])]
        adaptive=[excerpt('src/b.py',[(20,'def retry_rate_limit(): pass')])]
        result=choose_guarded(baseline,adaptive,'Where is retry rate limit?',
                              policy='query')
        self.assertEqual(result['choice'],'baseline')

    def test_source_ref_provenance_validation(self):
        baseline=[excerpt('src/a.py',[(1,'def foo(): pass')])]
        baseline[0]['source_refs']=['src/a.py:99']
        with self.assertRaises(ValueError):
            choose_guarded(baseline,[], 'Where is foo?')

    def test_total_budget_is_enforced(self):
        baseline=[excerpt('src/a.py',[(10,'def retry_rate_limit(): pass')])]
        with self.assertRaises(ValueError):
            choose_guarded(baseline,[], 'retry rate limit',max_chars=1)


if __name__=='__main__':
    unittest.main()
