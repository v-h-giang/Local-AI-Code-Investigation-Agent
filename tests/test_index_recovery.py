"""Offline recovery regressions without a real Ollama model or source indexing."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import os
import sqlite3
import tempfile
import unittest

from benchmark import run


class IndexRecoveryTests(unittest.TestCase):
    def test_benchmark_rebuilds_missing_embedding_in_configured_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            project=base/'agent-framework'
            project.mkdir()
            intelligence=base/'code_intelligence.sqlite'
            intelligence.touch()
            folder=base/'embeddings'
            folder.mkdir()
            args=SimpleNamespace(agent=Path('semantic_agent.py'),mode='ai',
                                 host='http://127.0.0.1:11434')
            calls=[]
            def fake_run(command,**kwargs):
                calls.append(command)
                db=Path(command[command.index('--db')+1])
                db.parent.mkdir(parents=True,exist_ok=True)
                with sqlite3.connect(db) as conn:
                    conn.execute('CREATE TABLE meta(key TEXT,value TEXT)')
                    conn.execute('INSERT INTO meta VALUES (?,?)',('root',str(project.resolve())))
                    conn.execute('CREATE TABLE chunks(path TEXT)')
                return SimpleNamespace(returncode=0)
            with patch.dict(os.environ,{'LOCAL_CODE_AGENT_EMBEDDING_DB':str(folder)}), \
                 patch.object(run.subprocess,'run',side_effect=fake_run):
                path=run.ensure_semantic_embedding_index(project,intelligence,args,base)
                self.assertEqual(path,folder/'agent-framework.sqlite')
                self.assertEqual(len(calls),1)
                again=run.ensure_semantic_embedding_index(project,intelligence,args,base)
                self.assertEqual(again,path)
                self.assertEqual(len(calls),1)

    def test_benchmark_does_not_rebuild_for_nonsemantic_agent(self):
        args=SimpleNamespace(agent=Path('agent.py'),mode='ai',
                             host='http://127.0.0.1:11434')
        self.assertIsNone(run.ensure_semantic_embedding_index(
            Path('dummy'),Path('dummy.sqlite'),args,Path('dummy')))

    def test_semantic_cli_missing_db_recovery_command(self):
        import semantic_agent
        import sys
        import types
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            project=base/'source'
            project.mkdir()
            db=base/'embeddings'
            db.mkdir()
            fake_agent=types.ModuleType('agent')
            fake_agent.main=lambda argv:0
            fake_ci=types.ModuleType('code_intelligence')
            fake_ci.search_file_candidates=lambda *a,**k:[]
            fake_loop=types.ModuleType('investigation_loop')
            fake_loop._validate_action=lambda action:action
            calls=[]
            def fake_run(command,**kwargs):
                calls.append(command)
                Path(command[command.index('--db')+1]).touch()
                return SimpleNamespace(returncode=0)
            with patch.dict(sys.modules,{'agent':fake_agent,
                                         'code_intelligence':fake_ci,
                                         'investigation_loop':fake_loop}), \
                 patch.dict(os.environ,{'LOCAL_CODE_AGENT_PREFETCH':'0'}), \
                 patch.object(semantic_agent.subprocess,'run',side_effect=fake_run):
                # The semantic wrapper needs available imports to proceed.
                status=semantic_agent.main([
                    '--semantic-db',str(db),'--project',str(project),
                    'investigate','where is checkpoint'])
            self.assertEqual(status,0)
            self.assertEqual(len(calls),1)
            self.assertEqual(Path(calls[0][calls[0].index('--db')+1]),
                             db/'source.sqlite')


if __name__=='__main__':
    unittest.main()
