from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self._skip=0
    def handle_starttag(self,tag,attrs):
        if tag.lower() in {'script','style','noscript'}: self._skip += 1
        elif tag.lower() in {'p','br','div','li','h1','h2','h3','h4','tr'} and not self._skip:self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag.lower() in {'script','style','noscript'} and self._skip:self._skip -= 1
        elif tag.lower() in {'p','div','li','h1','h2','h3','h4','tr'} and not self._skip:self.parts.append('\n')
    def handle_data(self,data):
        if not self._skip:self.parts.append(data)
    def text(self):
        s=''.join(self.parts);s=re.sub(r'[ \t]+',' ',s);s=re.sub(r'\n\s*\n+', '\n\n', s);return s.strip()


@dataclass
class Doc:
    source_id:str;title:str;text:str;source_url:str|None=None;effective_date:str|None=None


def load_sidecar(path:Path)->dict:
    choices=[path.with_suffix(path.suffix+'.meta.json'),path.with_suffix('.meta.json')]
    for p in choices:
        if p.is_file():
            try:return json.loads(p.read_text(encoding='utf-8'))
            except Exception as e:raise RuntimeError(f'Invalid metadata sidecar {p}: {e}') from e
    return {}


def normalize_doc(path:Path,text:str,meta:dict)->Doc:
    rel=path.relative_to(path.parents[1]) if len(path.parents)>=2 else path
    source_id=str(meta.get('source_id') or path.stem)
    title=str(meta.get('title') or path.stem.replace('_',' ').replace('-',' ').strip().title())
    return Doc(source_id=source_id,title=title,text=text.strip(),source_url=meta.get('source_url') or meta.get('url'),effective_date=meta.get('effective_date'))


def read_docs(path:Path)->Iterable[Doc]:
    if path.name.endswith('.meta.json'):return []
    meta=load_sidecar(path)
    suffix=path.suffix.lower()
    if suffix in {'.txt','.md'}:
        text=path.read_text(encoding='utf-8',errors='replace');return [normalize_doc(path,text,meta)]
    if suffix in {'.html','.htm'}:
        parser=TextExtractor();parser.feed(path.read_text(encoding='utf-8',errors='replace'));return [normalize_doc(path,parser.text(),meta)]
    if suffix=='.json':
        data=json.loads(path.read_text(encoding='utf-8'))
        rows=data if isinstance(data,list) else [data]
        out=[]
        for i,row in enumerate(rows):
            if isinstance(row,str):row={'text':row}
            if not isinstance(row,dict):continue
            text=str(row.get('text') or row.get('content') or '').strip()
            if not text:continue
            combined={**meta,**row};combined.setdefault('source_id',f'{path.stem}:{i+1}' if len(rows)>1 else path.stem)
            out.append(normalize_doc(path,text,combined))
        return out
    if suffix=='.csv':
        out=[]
        with path.open('r',encoding='utf-8-sig',newline='') as f:
            for i,row in enumerate(csv.DictReader(f),1):
                text=str(row.get('text') or row.get('content') or '').strip()
                if not text:continue
                combined={**meta,**{k:v for k,v in row.items() if v not in (None,'')}};combined.setdefault('source_id',f'{path.stem}:{i}')
                out.append(normalize_doc(path,text,combined))
        return out
    return []


def chunks(text:str,max_chars=1200,overlap_chars=160):
    paras=[re.sub(r'\s+',' ',p).strip() for p in re.split(r'\n\s*\n',text) if p.strip()]
    out=[];current=''
    for para in paras:
        if len(para)>max_chars:
            sentences=re.split(r'(?<=[.!?])\s+',para)
        else:sentences=[para]
        for part in sentences:
            if not part:continue
            candidate=(current+'\n'+part).strip() if current else part
            if len(candidate)<=max_chars:current=candidate;continue
            if current:out.append(current)
            carry=current[-overlap_chars:] if current and overlap_chars else ''
            current=(carry+' '+part).strip()
            while len(current)>max_chars:
                out.append(current[:max_chars]);current=current[max_chars-overlap_chars:].strip()
    if current:out.append(current)
    return out


def build(source_dir:Path,db_path:Path)->tuple[int,int]:
    if not source_dir.is_dir():
        raise FileNotFoundError(f'Knowledge source directory does not exist: {source_dir}')
    docs=[]
    for path in sorted(source_dir.rglob('*')):
        if path.is_file():
            docs.extend(read_docs(path))
    ids={}
    for doc in docs:
        if doc.source_id in ids:
            raise ValueError(f'Duplicate source_id {doc.source_id!r}: {ids[doc.source_id]} and {doc.title}. '
                             'Run tools/normalize_knowledge_sources.py and audit duplicated documents.')
        ids[doc.source_id]=doc.title
    db_path.parent.mkdir(parents=True,exist_ok=True);tmp=db_path.with_suffix(db_path.suffix+'.tmp');tmp.unlink(missing_ok=True)
    db=sqlite3.connect(tmp)
    try:
        db.executescript('''
        PRAGMA journal_mode=DELETE;
        CREATE TABLE documents(
            id INTEGER PRIMARY KEY,
            source_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            source_url TEXT,
            effective_date TEXT,
            sha256 TEXT NOT NULL
        );
        CREATE TABLE chunks(
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id),
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            text, title, source_id, source_url,
            tokenize='unicode61 remove_diacritics 2'
        );
        ''')
        chunk_count=0
        for doc in docs:
            digest=hashlib.sha256(doc.text.encode('utf-8')).hexdigest()
            cur=db.execute('INSERT INTO documents(source_id,title,source_url,effective_date,sha256) VALUES(?,?,?,?,?)',(doc.source_id,doc.title,doc.source_url,doc.effective_date,digest));did=cur.lastrowid
            for idx,text in enumerate(chunks(doc.text)):
                cur=db.execute('INSERT INTO chunks(document_id,chunk_index,text) VALUES(?,?,?)',(did,idx,text));cid=cur.lastrowid
                db.execute('INSERT INTO chunks_fts(rowid,text,title,source_id,source_url) VALUES(?,?,?,?,?)',(cid,text,doc.title,doc.source_id,doc.source_url or ''));chunk_count+=1
        db.commit()
    finally:db.close()
    tmp.replace(db_path)
    return len(docs),chunk_count


def main():
    p=argparse.ArgumentParser(description='Compile curated offline documents into the Automaton SQLite/FTS5 knowledge base')
    p.add_argument('--source-dir',type=Path,default=ROOT/'knowledge/sources')
    p.add_argument('--db',type=Path,default=ROOT/'runtime/knowledge.sqlite3')
    p.add_argument('--audit', action='store_true', help='Inspect source count and duplicates without modifying SQLite')
    a=p.parse_args()
    if a.audit:
        source=a.source_dir
        if not source.is_dir():p.error(f'Source directory absent: {source}')
        paths=[x for x in source.rglob('*') if x.suffix.lower() in {'.md','.txt','.html','.htm','.json','.csv'}
               and x.is_file() and not x.name.endswith('.meta.json')]
        print(f'Source directory: {source}');print(f'Readable source files: {len(paths)}')
        nested=source/'knowledge'/'sources'
        if nested.exists():print(f'WARNING: nested extraction detected: {nested}')
        from collections import Counter
        ids=Counter(d.source_id for path in paths for d in read_docs(path))
        print(f'Unique source IDs: {len(ids)}')
        for id_,count in sorted(ids.items()):
            if count>1:print(f'WARNING duplicate source ID: {id_} ({count})')
        return
    docs,chs=build(a.source_dir,a.db);print(f'Built {a.db} from {docs} documents / {chs} chunks.')
    if docs==0:print('No source documents were found. Add .md/.txt/.html/.json/.csv files under knowledge/sources/.')
if __name__=='__main__':main()
