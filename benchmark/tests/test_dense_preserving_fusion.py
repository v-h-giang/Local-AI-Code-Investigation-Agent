"""Gold-blind checks for hybrid-head / Dense-tail candidate fusion."""
import unittest

from dense_preserving_fusion import (hybrid_head_dense_tail,
    hybrid_head_interleaved_tail, hybrid_head_rrf_tail)


class DensePreservingFusionTests(unittest.TestCase):
    def test_preserves_top_eight_hybrid_paths_and_windows(self):
        hybrid=[{'path':f'src/h{i}.f90','line_hint':10+i,
                 'line_start':i+1,'line_end':i+9,
                 'citation':False} for i in range(12)]
        dense=[{'path':f'src/d{i}.f90','start_line':100+i,
                'end_line':120+i,'similarity':0.7} for i in range(30)]
        before=[dict(row) for row in hybrid]
        result=hybrid_head_dense_tail(hybrid,dense,limit=20)
        self.assertEqual([x['path'] for x in result[:8]],
                         [x['path'] for x in hybrid[:8]])
        self.assertEqual([(x['line_start'],x['line_end'])
                          for x in result[:8]],
                         [(x['line_start'],x['line_end'])
                          for x in hybrid[:8]])
        self.assertEqual(result[8]['path'],'src/d0.f90')
        self.assertEqual(result[8]['line_start'],100)
        self.assertEqual(result[8]['line_end'],120)
        self.assertEqual(result[8]['line_hint_source'],'dense')
        self.assertTrue(all(x['citation'] is False for x in result))
        self.assertEqual(hybrid,before)

    def test_deduplicates_and_keeps_dense_chance(self):
        hybrid=[{'path':f'src/h{i}.f90','line_start':1,
                 'line_end':8} for i in range(10)]
        dense=[{'path':'src/h1.f90','start_line':90,'end_line':95},
               {'path':'src/new.f90','start_line':21,'end_line':40},
               {'path':'src/new.f90','start_line':50,'end_line':60}]
        result=hybrid_head_dense_tail(hybrid,dense,limit=12)
        paths=[x['path'] for x in result]
        self.assertEqual(paths[:8],[x['path'] for x in hybrid[:8]])
        self.assertEqual(paths.count('src/new.f90'),1)
        self.assertEqual(paths[8],'src/new.f90')
        self.assertEqual(paths[-2:],['src/h8.f90','src/h9.f90'])

    def test_bounded_under_short_limit(self):
        hybrid=[{'path':f'f{i}.f90'} for i in range(12)]
        dense=[{'path':'d.f90','start_line':1,'end_line':5}]
        result=hybrid_head_dense_tail(hybrid,dense,limit=6,head=8)
        self.assertEqual([x['path'] for x in result],
                         [f'f{i}.f90' for i in range(6)])

    def test_degenerate_fallback_when_dense_empty(self):
        hybrid=[{'path':f'f{i}.f90'} for i in range(10)]
        self.assertEqual([x['path'] for x in
                          hybrid_head_dense_tail(hybrid,[],limit=10)],
                         [x['path'] for x in hybrid])


    def test_interleaved_tail_preserves_head_and_alternates(self):
        hybrid=[{'path':f'h{i}.py','line_start':i+1,'line_end':i+10}
                for i in range(12)]
        dense=[{'path':f'd{i}.py','start_line':100+i,'end_line':110+i}
               for i in range(12)]
        rows=hybrid_head_interleaved_tail(hybrid,dense,limit=14,head=8)
        self.assertEqual([r['path'] for r in rows[:8]],
                         [r['path'] for r in hybrid[:8]])
        self.assertEqual([r['path'] for r in rows[8:14]],
                         ['d0.py','h8.py','d1.py','h9.py','d2.py','h10.py'])
        self.assertEqual(rows[8]['line_start'],100)
        self.assertTrue(all(not row['citation'] for row in rows))

    def test_rrf_tail_prefers_items_supported_by_both_views(self):
        hybrid=[{'path':f'h{i}.py','line_start':i+1,'line_end':i+10}
                for i in range(8)]
        hybrid += [{'path':'overlap.py','line_start':1,'line_end':10},
                   {'path':'hybrid_only.py','line_start':20,'line_end':30}]
        dense=[{'path':'dense_only.py','start_line':10,'end_line':16},
               {'path':'overlap.py','start_line':80,'end_line':120}]
        rows=hybrid_head_rrf_tail(hybrid,dense,limit=11,head=8)
        self.assertEqual([r['path'] for r in rows[:8]],
                         [r['path'] for r in hybrid[:8]])
        self.assertEqual(rows[8]['path'],'overlap.py')
        self.assertEqual(rows[8]['tail_views'],['hybrid','dense'])
        self.assertEqual((rows[8]['line_start'],rows[8]['line_end']),(80,120))
        self.assertFalse(rows[8]['citation'])

    def test_tail_methods_fall_back_on_duplicate_or_empty(self):
        hybrid=[{'path':f'h{i}.f90'} for i in range(10)]
        dense=[{'path':'h1.f90'}, {'path':'only_dense.f90'}]
        for method in (hybrid_head_interleaved_tail,hybrid_head_rrf_tail):
            rows=method(hybrid,dense,limit=11)
            paths=[row['path'] for row in rows]
            self.assertEqual(paths[:8],[r['path'] for r in hybrid[:8]])
            self.assertEqual(len(paths),len(set(paths)))
            self.assertIn('only_dense.f90',paths)


if __name__=='__main__':
    unittest.main()
