"""Local Code Investigation Agent - CLI for Windows/VS Code."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from codebase import Repo
from agent_core import Investigator, Ollama, OllamaError
from exporter import export_design, export_static


def main(argv=None):
    p = argparse.ArgumentParser(description='Read-only local AI investigation of Java / SQL / Adobe AIR source')
    p.add_argument('--project', required=True, help='Local source project directory')
    p.add_argument('--model', default='qwen3:8b', help='Ollama local model tag (default qwen3:8b)')
    p.add_argument('--host', default='http://127.0.0.1:11434', help='Loopback Ollama endpoint')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Verify Ollama and report source summary')
    sub.add_parser('index', help='Rebuild local SQLite FTS search index')
    s = sub.add_parser('search', help='Literal source search without AI')
    s.add_argument('query'); s.add_argument('--pattern', default='*'); s.add_argument('--limit', type=int,default=30)
    s = sub.add_parser('refs', help='Find symbol references without AI'); s.add_argument('symbol')
    s = sub.add_parser('read', help='Read a file with line numbers'); s.add_argument('path'); s.add_argument('--start',type=int,default=1); s.add_argument('--end',type=int,default=120)
    s = sub.add_parser('ask', help='Ask one AI question'); s.add_argument('question')
    sub.add_parser('chat',help='Interactive session; /exit to quit')
    s = sub.add_parser('report',help='Generate offline static inventory and editable .drawio diagram')
    s.add_argument('--topic',default=''); s.add_argument('--out',default='output')
    s = sub.add_parser('design',help='Investigate with AI and export design.md + drawio')
    s.add_argument('--topic',required=True); s.add_argument('--out',default='output')
    a = p.parse_args(argv)
    try:
        repo = Repo(a.project)
        if a.command=='index': print(json.dumps(repo.index(),ensure_ascii=False,indent=2));return 0
        if a.command=='search': print(repo.search_code(a.query, a.pattern, a.limit));return 0
        if a.command=='refs': print(repo.find_symbol(a.symbol));return 0
        if a.command=='read': print(repo.read_file(a.path,a.start,a.end));return 0
        if a.command=='report': print(json.dumps(export_static(repo,a.topic,a.out),ensure_ascii=False,indent=2));return 0
        llm = Ollama(a.host, a.model)
        if a.command=='doctor':
            print(f'Project: {repo.root}\nSample files:\n{repo.list_files(limit=15)}\n{llm.health()}')
            return 0
        if a.command=='design':
            print(json.dumps(export_design(repo,llm,a.topic,a.out),ensure_ascii=False,indent=2))
            return 0
        inv = Investigator(repo,llm)
        if a.command=='ask': print('\n'+inv.ask(a.question));return 0
        if a.command=='chat':
            print('Local AI Code Agent - nhập /exit để thoát; /clear để xóa lịch sử.')
            while True:
                try: question=input('\nBạn> ').strip()
                except (EOFError,KeyboardInterrupt):break
                if question.lower() in ('/exit','exit','quit'):break
                if question.lower()=='/clear': inv=Investigator(repo,llm);print('Đã xóa lịch sử.');continue
                if question: print('\nAgent> '+inv.ask(question))
            return 0
    except (OllamaError,ValueError,OSError,KeyboardInterrupt) as e:
        print('ERROR:',e,file=sys.stderr);return 1
    return 0

if __name__=='__main__':
    sys.exit(main())
