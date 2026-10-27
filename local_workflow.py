"""Read-only, local-only bounded LLM calls and persistent checkpoints.

This module does not open network connections: production calls are delegated to the
Ollama client, which independently enforces HTTP loopback. Checkpoints and cache are
written exclusively under the configured output/middle-files directory.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path


class CallBudgetExceeded(RuntimeError):
    """Stop a workflow instead of silently exceeding its configured LLM budget."""


def digest(value):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def json_object(raw):
    """Parse bounded JSON response (including fenced markdown); no eval."""
    text = str(raw or '').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        begin, end = text.find('{'), text.rfind('}')
        if begin < 0 or end <= begin:
            raise ValueError('Qwen did not return a JSON object')
        result = json.loads(text[begin:end+1])
    if not isinstance(result, dict):
        raise ValueError('Qwen JSON must be an object')
    return result


class LocalCallBudget:
    """One sequential Ollama model across steps, with audit, disk cache and hard cap."""
    def __init__(self, llm, out, max_calls=80, resume=True):
        if not 1 <= int(max_calls) <= 5000:
            raise ValueError('max-llm-calls must be between 1 and 5000')
        self.llm = llm
        self.max_calls = int(max_calls)
        self.calls_used = 0
        self.cache_hits = 0
        self.resume = bool(resume)
        self.base = Path(out).expanduser().resolve() / 'middle-files' / 'workflow'
        self.cache = self.base / 'llm_cache'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.base / 'call_audit.jsonl'
        model_name = getattr(llm, 'model', 'local-ollama')
        self.model = model_name if isinstance(model_name, str) else 'local-ollama'
        ctx = getattr(llm, 'num_ctx', 2048)
        self.num_ctx = ctx if isinstance(ctx, int) else 2048
        # Prevent adapting this wrapper to a remote Ollama endpoint.
        host = getattr(llm, 'host', None)
        if isinstance(host, str):
            from urllib.parse import urlsplit
            parsed = urlsplit(host)
            if parsed.scheme != 'http' or parsed.hostname not in ('localhost','127.0.0.1','::1'):
                raise ValueError('Only local loopback Ollama is permitted')

    def call(self, messages, tools=False, num_predict=None, **kwargs):
        key = digest({'version':2, 'model':self.model, 'ctx':self.num_ctx,
                      'messages':messages, 'tools':tools, 'num_predict':num_predict,
                      'kwargs':kwargs})
        target = self.cache / (key + '.json')
        if self.resume and target.exists():
            try:
                obj = json.loads(target.read_text(encoding='utf-8'))
                if isinstance(obj, dict) and isinstance(obj.get('message'), dict):
                    self.cache_hits += 1
                    return obj['message']
            except (OSError, ValueError):
                pass
        if self.calls_used >= self.max_calls:
            raise CallBudgetExceeded(f'Local LLM call limit reached: {self.max_calls}')
        self.calls_used += 1
        args = {'tools':tools, **kwargs}
        if num_predict is not None:
            args['num_predict'] = num_predict
        try:
            response = self.llm.call(messages, **args)
            if not isinstance(response, dict):
                raise ValueError('Expected dict from Ollama')
            atomic_json(target, {'message':response, 'model':self.model})
        except Exception as exc:
            with self.audit_path.open('a', encoding='utf-8') as fp:
                fp.write(json.dumps({'key':key,'model':self.model,'status':'failed',
                                     'error_type':type(exc).__name__},ensure_ascii=False)+'\n')
            raise
        # Store no prompt/evidence in audit; they live only in the local cache.
        with self.audit_path.open('a', encoding='utf-8') as fp:
            fp.write(json.dumps({'key':key,'model':self.model,'status':'completed'}, ensure_ascii=False)+'\n')
        return response

    def usage(self):
        return {'model':self.model,'llm_calls':self.calls_used,'cache_hits':self.cache_hits,
                'max_calls':self.max_calls,'audit':str(self.audit_path)}


class WorkflowState:
    """Persistent, inspectable stage state. Never stores API credentials or source text."""
    def __init__(self, out):
        self.path=Path(out).expanduser().resolve()/'middle-files'/'workflow'/'state.json'
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            self.data=data if isinstance(data,dict) and data.get('version')==1 else {'version':1,'stages':{}}
        except (ValueError,OSError):
            self.data={'version':1,'stages':{}}

    def record(self,stage,status,**metadata):
        if status not in ('completed','partial','failed','skipped'):
            raise ValueError('Invalid stage state')
        self.data['stages'][str(stage)]={'status':status,**metadata}
        atomic_json(self.path,self.data)
