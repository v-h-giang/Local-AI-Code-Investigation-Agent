"""Local Code Investigation Agent - CLI for Windows/VS Code."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from codebase import Repo
from agent_core import Investigator, Ollama, OllamaError
from exporter import export_design, export_static
from overview import export_overview
from system_memory import print_ram_status


def main(argv=None):
    p = argparse.ArgumentParser(description='Read-only local AI investigation of Java / SQL / Adobe AIR source')
    p.add_argument('--project', required=True, help='Local source project directory')
    p.add_argument('--model', default='qwen3:8b', help='Ollama local model tag (default qwen3:8b)')
    p.add_argument('--host', default='http://127.0.0.1:11434', help='Loopback Ollama endpoint')
    p.add_argument('--num-ctx', type=int, default=2048, help='Ollama context tokens (default 2048, suitable for limited RAM)')
    p.add_argument('--timeout', type=int, default=240, help='HTTP response timeout in seconds (default 240)')
    sub = p.add_subparsers(dest='command', required=True)
    kb = sub.add_parser('knowledge',help='Manage offline global programming knowledge base')
    kb.add_argument('operation',choices=('build','query','status'))
    kb.add_argument('question',nargs='?',default='')
    kb.add_argument('--kb-path',default=None,help='Optional SQLite knowledge DB location')
    kb.add_argument('--pack-dir',default=None,help='Local JSON pack directory for build')
    li = sub.add_parser('lsp-import',help='Import a pre-exported LSP JSON symbol-location array')
    li.add_argument('file',help='Local JSON file; this never launches a language server')
    li.add_argument('--out',default='output/architecture')
    ls = sub.add_parser('lsp-symbol',help='Find previously imported LSP symbol locations')
    ls.add_argument('symbol')
    ls.add_argument('--out',default='output/architecture')
    d = sub.add_parser('doctor', help='Verify Ollama and report source summary')
    d.add_argument('--probe', action='store_true', help='Actually load model and generate a tiny reply')
    sub.add_parser('index', help='Rebuild local SQLite FTS search index')
    s = sub.add_parser('architecture', help='Static scan by default; --auto-investigate-top starts the full local Qwen workflow')
    s.add_argument('--out', default='output/architecture', help='Output folder')
    s.add_argument('--ai-summary', action='store_true', help='Summarize each module using local Ollama (optional)')
    s.add_argument('--auto-investigate-top',type=lambda value: 20 if value.lower() == 'max' else int(value),
                   nargs='?',const=5,default=0,metavar='N|max',
                   help='Complete local workflow: omit value for Top 5; use 1-20 or max for every generated question (up to 20)')
    s.add_argument('--ai-suggestions',action='store_true',help='Qwen ranks and critiques source-backed question candidates (also on with --auto-investigate-top)')
    s.add_argument('--non-ai-suggestions','--no-ai-suggestions',action='store_true',dest='no_ai_suggestions',
                   help='Skip local Qwen question ranking; use source-grounded deterministic ordering')
    s.add_argument('--question-review-rounds',type=int,default=2,help='Local Qwen question ranking passes, 1-3 (default 2)')
    s.add_argument('--investigation-review-rounds',type=int,default=1,help='Evidence critic passes per investigation, 0-2')
    s.add_argument('--non-investigation-review',action='store_true',help='Skip extra Qwen evidence-review passes for investigations')
    s.add_argument('--synthesize',action='store_true',help='Generate system report even without --auto-investigate-top (already on when auto investigation is enabled)')
    s.add_argument('--non-synthesize','--non-synthesis',action='store_true',dest='non_synthesize',
                   help='Skip final system-knowledge synthesis in the automatic workflow')
    s.add_argument('--synthesis-review-rounds',type=int,default=2,help='System synthesis critic passes, 0-2')
    s.add_argument('--non-synthesis-review',action='store_true',help='Skip Qwen critic passes during final synthesis')
    s.add_argument('--non-review',action='store_true',help='Skip extra Qwen critique passes in question ranking, investigations and synthesis')
    s.add_argument('--max-llm-calls',type=int,default=None,
                   help='Hard local Ollama call limit; auto workflow default 160, otherwise 80')
    s = sub.add_parser('intelligence', help='Incrementally build symbol/call/search/SQL intelligence index')
    s.add_argument('--out', default='output/architecture')
    s = sub.add_parser('investigate', help='Investigate with local Qwen by default; --non-ai for retrieval only')
    s.add_argument('question'); s.add_argument('--budget',type=int,default=2400)
    s.add_argument('--max-steps',type=int,default=4,help='Maximum read-only tool investigation steps (1-6)')
    s.add_argument('--review-rounds',type=int,default=1,help='Local Qwen evidence review passes (0-2)')
    s.add_argument('--max-llm-calls',type=int,default=80,help='Hard limit for this investigation')
    s.add_argument('--non-ai',action='store_true',help='Disable Qwen and use local lexical evidence retrieval only')
    for command_name in ('architecture', 'investigate'):
        target = sub.choices[command_name]
        target.add_argument('--non-markdown', '--no-markdown', action='store_true', dest='no_markdown',
                            help='Skip Markdown output for individual investigations (not architecture.md)')
        target.add_argument('--non-diagram', '--no-diagram', action='store_true', dest='no_diagram',
                            help='Skip each individual investigation.drawio')
        target.add_argument('--non-update-drawio', '--no-update-drawio', action='store_true', dest='no_update_drawio',
                            help='Do not generate annotated versions of the architecture diagrams')
        target.add_argument('--overwrite-drawio', action='store_true',
                            help='Explicitly update original Draw.io files; backups in middle-files/drawio-baselines')
        target.add_argument('--diagram-type', choices=('auto', 'flow', 'impact', 'symbol'),
                            default='auto', help='Evidence-diagram type (never invents execution links)')
    s = sub.add_parser('synthesize',help='Hierarchical local Qwen synthesis of architecture and prior investigations')
    s.add_argument('--out',default='output/architecture',help='Existing architecture output folder')
    s.add_argument('--review-rounds',type=int,default=2,help='Final local evidence-review passes (0-2)')
    s.add_argument('--max-llm-calls',type=int,default=80,help='Hard limit for Ollama calls')
    s.add_argument('--fresh',action='store_true',help='Ignore previous synthesis checkpoints')
    for report_command in ('architecture', 'investigate', 'synthesize'):
        sub.choices[report_command].add_argument('--report-format',
            choices=('html','md','both'),default='html',
            help='Human-readable reports: html (default), md, or both')
    s = sub.add_parser('symbol',help='Symbol declarations and references from local intelligence index')
    s.add_argument('name')
    s = sub.add_parser('trace',help='Candidate caller-callee and static dependency graph')
    s.add_argument('name'); s.add_argument('--depth',type=int,default=3)
    s.add_argument('--direction',choices=['out','in'],default='out')
    s = sub.add_parser('impact',help='Reverse dependency and caller impact candidates')
    s.add_argument('name');s.add_argument('--depth',type=int,default=4)
    s = sub.add_parser('clusters',help='Connected code graph components')
    s = sub.add_parser('flows',help='Entrypoint, dependency, and SQL evidence inventory')
    s = sub.add_parser('diff-impact',help='Trace file impact from local Git diff')
    s.add_argument('--base',default='HEAD~1');s.add_argument('--head',default='HEAD')
    s = sub.add_parser('vectorize',help='Optional bounded local Ollama symbol embedding index')
    s.add_argument('--embedding-model',default='nomic-embed-text');s.add_argument('--max-symbols',type=int,default=200)
    s = sub.add_parser('semantic',help='Vector similarity across locally embedded symbol signatures')
    s.add_argument('query');s.add_argument('--embedding-model',default='nomic-embed-text')
    s = sub.add_parser('history',help='Read local Git history for code investigation')
    s.add_argument('--file',default=None);s.add_argument('--limit',type=int,default=20)
    for cmd_name in ('investigate','symbol','trace','impact','clusters','flows','history','diff-impact','vectorize','semantic'):
        sub.choices[cmd_name].add_argument('--out',default='output/architecture',help='Index/output directory')
    s = sub.add_parser('search', help='Literal source search without AI')
    s.add_argument('query'); s.add_argument('--pattern', default='*'); s.add_argument('--limit', type=int,default=30)
    s = sub.add_parser('refs', help='Find symbol references without AI'); s.add_argument('symbol')
    s = sub.add_parser('read', help='Read a file with line numbers'); s.add_argument('path'); s.add_argument('--start',type=int,default=1); s.add_argument('--end',type=int,default=120)
    s = sub.add_parser('ask', help='Ask one AI question'); s.add_argument('question')
    sub.add_parser('chat',help='Interactive session; /exit to quit')
    s = sub.add_parser('report',help='Generate offline static inventory and editable .drawio diagram')
    s.add_argument('--topic',default=''); s.add_argument('--out',default='output')
    s = sub.add_parser('overview',help='Automatically survey the full repository without a topic (optional AI)')
    s.add_argument('--out',default='output/overview'); s.add_argument('--ai',action='store_true',help='Also write AI architecture design using local Ollama')
    s.add_argument('--max-batches',type=int,default=None,help='Optional debug-only cap; default: no limit'); s.add_argument('--files-per-batch',type=int,choices=[1,2],default=1); s.add_argument('--no-resume',action='store_true')
    s = sub.add_parser('design',help='With --topic: feature design; without --topic: automated repo overview + AI')
    s.add_argument('--topic',default=''); s.add_argument('--out',default=None)
    s.add_argument('--max-batches',type=int,default=None,help='Optional debug-only cap; default: no limit'); s.add_argument('--files-per-batch',type=int,choices=[1,2],default=1); s.add_argument('--no-resume',action='store_true')
    a = p.parse_args(argv)
    # Automatic investigation is an opt-in switch, but once enabled it activates
    # the complete recommended workflow without a long list of positive flags.
    # A 'non-' flag always takes precedence over the corresponding default.
    if a.command == 'architecture':
        a.synthesize = (a.synthesize or a.auto_investigate_top > 0) and not a.non_synthesize
        if a.non_review:
            a.question_review_rounds = 1  # Still rank candidates once; skip ranking critique.
        if a.non_investigation_review or a.non_review:
            a.investigation_review_rounds = 0
        if a.non_synthesis_review or a.non_review:
            a.synthesis_review_rounds = 0
        if a.max_llm_calls is None:
            a.max_llm_calls = (160 + max(0, a.auto_investigate_top - 5) * 14) if a.auto_investigate_top > 0 else 80
    report_session = None
    if a.command in ('architecture','investigate','synthesize'):
        from report_render import ReportSession
        # HTML-only runs preserve Markdown evidence in middle-files and restore
        # it before reuse by architecture cache or hierarchical synthesis.
        report_session = ReportSession(a.out,a.report_format)
        report_session.restore()
    print_ram_status()
    try:
        if a.command=='knowledge':
            from knowledge_base import build_knowledge, query_knowledge, knowledge_status
            if a.operation=='build':
                result=build_knowledge(db_path=a.kb_path,pack_dir=a.pack_dir)
            elif a.operation=='query':
                if not a.question.strip():
                    raise ValueError('knowledge query requires a question')
                result={'question':a.question,'concepts':query_knowledge(
                    a.question,db_path=a.kb_path)}
            else:
                result=knowledge_status(db_path=a.kb_path)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0
        if a.command in ('lsp-import','lsp-symbol'):
            from lsp_bridge import import_lsp_locations,lookup_lsp_locations
            repo.intelligence_db=(Path(a.out).expanduser().resolve()/
                                  'middle-files'/'code_intelligence.sqlite')
            result=(import_lsp_locations(repo,a.file)
                    if a.command=='lsp-import'
                    else lookup_lsp_locations(repo,a.symbol))
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0
        if a.command in ('architecture','investigate','synthesize') and not 1 <= a.max_llm_calls <= 5000:
            raise ValueError('--max-llm-calls must be 1..5000')
        if a.command=='architecture' and a.ai_suggestions and a.no_ai_suggestions:
            raise ValueError('--ai-suggestions conflicts with --non-ai-suggestions')
        if a.command=='architecture' and a.synthesize and a.non_synthesize and a.auto_investigate_top == 0:
            # The user's explicit disable switch takes precedence.
            a.synthesize = False
        if a.command=='architecture' and (a.auto_investigate_top < 0 or a.auto_investigate_top > 20):
            raise ValueError('--auto-investigate-top must be 1..20, max, or omitted')
        if a.command in ('architecture','investigate') and a.no_update_drawio and a.overwrite_drawio:
            raise ValueError('--overwrite-drawio cannot be combined with --no-update-drawio')
        repo = Repo(a.project)
        if a.command=='index': print(json.dumps(repo.index(),ensure_ascii=False,indent=2));return 0
        if a.command=='architecture':
            from architecture import export_architecture
            from module_summary import summarize_modules
            result = export_architecture(repo,a.out)
            from local_workflow import WorkflowState, atomic_json
            state=WorkflowState(a.out)
            state.record('architecture','completed',files=result.get('files_scanned'))
            if a.auto_investigate_top:
                workflow_settings={
                    'auto_investigate_top':a.auto_investigate_top,
                    'report_format':a.report_format,
                    'local_ai_question_ranking':not a.no_ai_suggestions,
                    'question_review_rounds':a.question_review_rounds if not a.no_ai_suggestions else 0,
                    'investigation_review_rounds':a.investigation_review_rounds,
                    'synthesize':a.synthesize,
                    'synthesis_review_rounds':a.synthesis_review_rounds if a.synthesize else 0,
                    'max_llm_calls':a.max_llm_calls,
                    'model':a.model,
                    'num_ctx':a.num_ctx,
                    'ai_module_summaries':a.ai_summary,
                    'markdown':not a.no_markdown,
                    'diagram':not a.no_diagram,
                    'annotate_drawio':not a.no_update_drawio,
                }
                atomic_json(Path(a.out).expanduser().resolve()/'middle-files'/'workflow'/'config.json',workflow_settings)
            needs_local_ai=(a.ai_suggestions or a.auto_investigate_top>0 or a.synthesize or a.ai_summary)
            workflow_llm=None
            if needs_local_ai:
                from local_workflow import LocalCallBudget
                workflow_llm=LocalCallBudget(Ollama(a.host,a.model,timeout=a.timeout,num_ctx=a.num_ctx),
                                             a.out,max_calls=a.max_llm_calls)
            result.update(summarize_modules(repo,a.out,llm=workflow_llm if a.ai_summary else None))
            from stack_architecture import export_stack_architecture
            result.update(export_stack_architecture(repo,a.out))
            from suggested_investigations import suggest_investigations, auto_investigate
            rank_with_qwen=(a.ai_suggestions or a.auto_investigate_top>0) and not a.no_ai_suggestions
            if not 1 <= a.question_review_rounds <= 3:
                raise ValueError('--question-review-rounds must be between 1 and 3')
            if not 0 <= a.investigation_review_rounds <= 2 or not 0 <= a.synthesis_review_rounds <= 2:
                raise ValueError('Review rounds must be between 0 and 2')
            suggestions = suggest_investigations(repo,a.out,top=20,
                llm=workflow_llm if rank_with_qwen else None,ai_rounds=a.question_review_rounds)
            candidates = suggestions.pop('candidates')
            result.update(suggestions)
            state.record('suggested_investigations','completed',count=result['suggestions_count'],
                         ranking=suggestions.get('ranking_method','static-heuristic'))
            failed=False
            if a.auto_investigate_top:
                result['auto_investigation'] = auto_investigate(repo,a.out,candidates,
                    a.auto_investigate_top,workflow_llm,review_rounds=a.investigation_review_rounds,
                    markdown=(not a.no_markdown or a.report_format!='md'), diagram=not a.no_diagram,
                    update_drawio=not a.no_update_drawio,
                    overwrite_drawio=a.overwrite_drawio, diagram_type=a.diagram_type)
                failed=(result['auto_investigation']['successful'] != result['auto_investigation']['executed'])
                state.record('auto_investigations','partial' if failed else 'completed',
                    requested=a.auto_investigate_top, completed=result['auto_investigation']['successful'])
            if a.synthesize:
                from synthesis_workflow import synthesize
                result['synthesis']=synthesize(repo,a.out,workflow_llm,review_rounds=a.synthesis_review_rounds)
                state.record('synthesis',result['synthesis']['status'] if result['synthesis']['status'] in ('completed','partial','failed') else 'partial',
                    modules=result['synthesis'].get('modules'),report=result['synthesis'].get('report'))
                failed=failed or result['synthesis']['status']!='completed'
            if a.auto_investigate_top:
                result['workflow_settings']=workflow_settings
            if workflow_llm:result['workflow_usage']=workflow_llm.usage()
            report_session.finalize()
            result=report_session.report_paths(result)
            result['report_format']=a.report_format
            print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if failed else 0
        if a.command=='synthesize':
            if not 0 <= a.review_rounds <= 2:raise ValueError('--review-rounds must be 0..2')
            from local_workflow import LocalCallBudget
            from synthesis_workflow import synthesize
            llm=LocalCallBudget(Ollama(a.host,a.model,timeout=a.timeout,num_ctx=a.num_ctx),
                                a.out,max_calls=a.max_llm_calls,resume=not a.fresh)
            result=synthesize(repo,a.out,llm,review_rounds=a.review_rounds,fresh=a.fresh)
            from local_workflow import WorkflowState
            WorkflowState(a.out).record('synthesis',result['status'] if result['status'] in ('completed','partial','failed') else 'partial',report=result.get('report'))
            result['workflow_usage']=llm.usage()
            report_session.finalize()
            result=report_session.report_paths(result)
            result['report_format']=a.report_format
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if result['status']=='completed' else 2
        if a.command in ('intelligence','investigate','symbol','trace','impact','clusters','flows','history','diff-impact','vectorize','semantic'):
            from code_intelligence import (build_intelligence, investigate, symbol_query, trace,
                impact, clusters, business_flows, git_history, diff_impact, vectorize, vector_search)
            repo.intelligence_db=(Path(a.out).expanduser().resolve()/'middle-files'/'code_intelligence.sqlite')
            if a.command=='intelligence': result=build_intelligence(repo,a.out)
            elif a.command=='history':result=git_history(repo,a.file,a.limit)
            elif a.command=='diff-impact':result=diff_impact(repo,a.base,a.head)
            elif a.command=='vectorize':result=vectorize(repo,a.host,a.embedding_model,a.max_symbols)
            elif a.command=='semantic':result=vector_search(repo,a.query,a.host,a.embedding_model)
            elif a.command=='symbol':result=symbol_query(repo,a.name)
            elif a.command=='trace':result=trace(repo,a.name,a.depth,a.direction)
            elif a.command=='impact':result=impact(repo,a.name,a.depth)
            elif a.command=='clusters':result=clusters(repo)
            elif a.command=='flows':result=business_flows(repo)
            else:
                if not 0 <= a.review_rounds <= 2:raise ValueError('--review-rounds must be 0..2')
                from local_workflow import LocalCallBudget
                llm=None if a.non_ai else LocalCallBudget(
                    Ollama(a.host,a.model,timeout=a.timeout,num_ctx=a.num_ctx),a.out,max_calls=a.max_llm_calls)
                result=investigate(repo,a.question,llm,budget=a.budget,max_steps=a.max_steps,
                                   review_rounds=a.review_rounds)
                from investigation_report import write_investigation
                effective_status='insufficient-evidence' if result.get('answer_status')=='insufficient-evidence' else 'completed'
                output=write_investigation(repo,a.out,result,question=a.question,status=effective_status,
                    markdown=(not a.no_markdown or a.report_format!='md'),diagram=not a.no_diagram,
                    update_drawio=not a.no_update_drawio,overwrite_drawio=a.overwrite_drawio,
                    diagram_type=a.diagram_type)
                # The terminal is human-readable. Raw investigation JSON lives under middle-files.
                report_session.finalize()
                output=report_session.report_paths(output)
                print('\n=== Investigation result ===')
                print('Status:',output['status'])
                print('Question:',a.question)
                if result.get('answer'):
                    print('\n'+str(result['answer']))
                elif result.get('source_excerpts'):
                    print('\nLexical search evidence (no AI inference):')
                    for excerpt in result['source_excerpts'][:6]:print(' -',str(excerpt)[:300])
                else:
                    print('No answer or source evidence found. See report and status.')
                if output.get('html'):print('\nHTML:',output['html'])
                if output.get('markdown'):print('\nMarkdown:',output['markdown'])
                if output.get('investigation_drawio'):print('Draw.io:',output['investigation_drawio'])
                if output.get('architecture_diagrams'):
                    updated=[x['diagram'] for x in output['architecture_diagrams'] if x.get('status')=='updated']
                    if updated: print('Annotated architecture diagrams:',len(updated),'(kept originals)')
                    else:print('Annotated architecture: no existing base Draw.io found; run architecture first.')
                print('Technical JSON:',output['json'])
                return 0
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0
        if a.command=='search': print(repo.search_code(a.query, a.pattern, a.limit));return 0
        if a.command=='refs': print(repo.find_symbol(a.symbol));return 0
        if a.command=='read': print(repo.read_file(a.path,a.start,a.end));return 0
        if a.command=='report': print(json.dumps(export_static(repo,a.topic,a.out),ensure_ascii=False,indent=2));return 0
        if a.command=='overview' and not a.ai:
            print(json.dumps(export_overview(repo,a.out),ensure_ascii=False,indent=2));return 0
        if a.command in ('ask', 'chat', 'design', 'overview'):
            print('[Index] Checking local source index...', flush=True)
            info = repo.ensure_index()
            print(f'[Index] {info["status"]}: {info["files"]} files; DB: {info["database"]}', flush=True)
        llm = Ollama(a.host, a.model, timeout=a.timeout, num_ctx=a.num_ctx)
        if a.command=='doctor':
            print(f'Project: {repo.root}\nSample files:\n{repo.list_files(limit=15)}\n{llm.health()}')
            if a.probe:
                print(llm.probe())
            return 0
        if a.command=='overview':
            print('[Overview] Surveying repository and generating outputs...', flush=True)
            result=export_overview(repo,a.out,llm=llm,max_batches=a.max_batches,files_per_batch=a.files_per_batch,resume=not a.no_resume)
            print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result.get('status')=='incomplete' else 0
        if a.command=='design':
            print('[Design] Analyzing source and writing documents...', flush=True)
            dest=a.out or ('output' if a.topic.strip() else 'output/overview')
            result = export_design(repo,llm,a.topic,dest) if a.topic.strip() else export_overview(repo,dest,llm=llm,max_batches=a.max_batches,files_per_batch=a.files_per_batch,resume=not a.no_resume)
            print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result.get('status')=='incomplete' else 0
        inv = Investigator(repo,llm)
        if a.command=='ask': print('\n'+inv.ask(a.question));return 0
        if a.command=='chat':
            print('Local AI Code Agent - /overview (quét offline), /design-all (AI overview), /exit, /clear.')
            while True:
                try: question=input('\nBạn> ').strip()
                except (EOFError,KeyboardInterrupt):break
                if question.lower() in ('/exit','exit','quit'):break
                if question.lower()=='/clear': inv=Investigator(repo,llm);print('Đã xóa lịch sử.');continue
                if question.lower() in ('/overview','/design-all'):
                    info=export_overview(repo,'output/overview',llm=llm if question.lower()=='/design-all' else None)
                    print(json.dumps(info,ensure_ascii=False,indent=2));continue
                if question: print('\nAgent> '+inv.ask(question))
            return 0
    except (OllamaError,ValueError,OSError,KeyboardInterrupt) as e:
        print('ERROR:',e,file=sys.stderr);return 1
    finally:
        if report_session is not None:
            # Also publish partial results if a later stage raises an error.
            report_session.finalize()
    return 0

if __name__=='__main__':
    sys.exit(main())
