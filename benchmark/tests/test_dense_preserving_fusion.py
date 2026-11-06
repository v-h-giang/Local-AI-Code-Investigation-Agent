"""Gold-blind checks for hybrid-head / Dense-tail candidate fusion."""
import unittest

from dense_preserving_fusion import hybrid_head_dense_tail


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


if __name__=='__main__':
    unittest.main()
