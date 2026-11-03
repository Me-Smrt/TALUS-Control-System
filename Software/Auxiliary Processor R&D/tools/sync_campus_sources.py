"""Opt-in campus-only crawl of public official Tennessee Tech pages.

Downloads source material for offline FTS5 indexing; never runs in TALUS' live
conversation path. Respects robots.txt, restricts domains and topic scope, and
records source URL and retrieval date in sidecars. Use --dry-run to list seeds.
"""
from __future__ import annotations
import argparse
import hashlib
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).resolve().parents[1]
UA = 'TALUSCampusKnowledgeBuilder/1.0 (educational offline index)'
SEEDS = (
    'https://www.tntech.edu/',
    'https://www.tntech.edu/maps/',
    'https://www.tntech.edu/parking/',
    'https://www.tntech.edu/parking/campus-parking.php',
    'https://www.tntech.edu/parents/campus.php',
    'https://www.tntech.edu/facstaff/',
    'https://www.tntech.edu/admissions/',
    'https://www.tntech.edu/dining/',
)
PATH_PREFIXES = (
    '/admissions/', '/academic/', '/academics/', '/calendar/', '/catalog/',
    '/financialaid/', '/scholarships/', '/bursar/', '/housing/', '/reslife/',
    '/dining/', '/parking/', '/maps/', '/students/', '/student/', '/parents/',
    '/library/', '/registrar/', '/records/', '/healthservices/', '/counseling/',
    '/recreation/', '/campus/', '/sga/', '/organizations/', '/it/', '/its/',
    '/tech-express/', '/tech-express', '/techexpress/', '/facstaff/', '/about/',
    '/orientation/', '/nsfp/', '/police/', '/universitypolice/', '/accessibility/',
)

def normalize(url: str) -> str | None:
    p=urlsplit(url)
    if p.scheme != 'https' or p.netloc.casefold() not in {'www.tntech.edu', 'tntech.edu'}:return None
    if not (p.path == '/' or p.path.startswith(PATH_PREFIXES)):return None
    if p.path.lower().endswith(('.pdf','.jpg','.png','.zip','.doc','.docx','.xlsx','.xml','.ics')):return None
    return urlunsplit(('https', 'www.tntech.edu', p.path or '/', '', ''))

class Page(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.text=[];self.title=[];self._skips=[];self._in_title=False
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs);tag=tag.lower()
        if tag in {'script','style','noscript','svg','nav','footer','header'}:self._skips.append(tag)
        if tag=='title':self._in_title=True
        if tag=='a' and not self._skips and attrs.get('href'):self.links.append(attrs['href'])
        if tag in {'h1','h2','h3','p','li','tr','br'} and not self._skips:self.text.append('\n')
    def handle_endtag(self, tag):
        tag=tag.lower()
        if tag=='title':self._in_title=False
        if tag in self._skips:self._skips=self._skips[:len(self._skips)-1-self._skips[::-1].index(tag)]
        if tag in {'p','li','tr'} and not self._skips:self.text.append('\n')
    def handle_data(self, data):
        if self._in_title:self.title.append(data)
        if not self._skips and not self._in_title:self.text.append(data)

def fetch(url, max_bytes=1_500_000):
    req=Request(url,headers={'User-Agent':UA,'Accept':'text/html'})
    with urlopen(req,timeout=20) as res:
        if 'text/html' not in res.headers.get('Content-Type','').lower():return None
        raw=res.read(max_bytes+1)
        if len(raw)>max_bytes:raise ValueError('oversized HTML response')
        encoding=res.headers.get_content_charset() or 'utf-8'
    page=Page();page.feed(raw.decode(encoding,errors='replace'))
    body=re.sub(r'\n[\s\n]*\n', '\n\n', re.sub(r'[ \t]+',' ',''.join(page.text))).strip()
    title=re.sub(r'\s+',' ',''.join(page.title)).strip() or urlsplit(url).path.strip('/') or 'Tech homepage'
    return title,body,page.links

def sync(output:Path,max_pages:int,delay:float):
    robot=RobotFileParser();robot.set_url('https://www.tntech.edu/robots.txt')
    try:robot.read()
    except Exception as exc:raise RuntimeError('Cannot verify robots.txt; refusing crawl') from exc
    queue=list(SEEDS);seen=set();count=0;output.mkdir(parents=True,exist_ok=True)
    existing_urls = set()
    for meta_path in output.rglob('*.meta.json'):
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            original = normalize(str(meta.get('source_url') or meta.get('url') or ''))
            if original: existing_urls.add(original)
        except (ValueError,OSError):pass
    while queue and count < max_pages:
        candidate=queue.pop(0);url=normalize(candidate)
        if not url or url in seen:continue
        seen.add(url)
        if not robot.can_fetch(UA,url):print('ROBOTS BLOCKED',url);continue
        try:
            fetched=fetch(url)
            if not fetched:continue
            title,body,links=fetched
            if len(body)<150:continue
            if url not in existing_urls:
                source_id='tech_'+hashlib.sha256(url.encode()).hexdigest()[:16]
                file=output/f'{source_id}.md'
                file.write_text(f'# {title}\n\n{body}\n',encoding='utf-8')
                metadata={'source_id':source_id,'title':title,'source_url':url,
                          'retrieved_at':datetime.now(timezone.utc).isoformat(), 'domain':'campus'}
                file.with_suffix('.meta.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
                count+=1;existing_urls.add(url)
                print(f'SAVED {count}/{max_pages}',title,url)
            else:
                print('PRESERVED existing curated source:',url)
            for link in links:
                child=normalize(urljoin(url,link))
                if child and child not in seen and child not in queue:queue.append(child)
        except Exception as exc:print('SKIPPED',url,str(exc))
        time.sleep(max(0.25,delay))
    print(f'Updated {count} official campus pages. Now run tools/build_knowledge_base.py.')

def main():
    p=argparse.ArgumentParser(description='Explicit opt-in official Tech campus source sync')
    p.add_argument('--max-pages',type=int,default=60)
    p.add_argument('--delay',type=float,default=1.2)
    p.add_argument('--source-dir',type=Path,default=ROOT/'knowledge/sources')
    p.add_argument('--fetch',action='store_true',help='Actually download public campus pages')
    a=p.parse_args()
    if a.max_pages<1 or a.max_pages>200:p.error('max-pages must be 1..200')
    if a.delay<0.25:p.error('delay must be >= 0.25 seconds')
    if not a.fetch:
        print('DRY RUN: no requests made. Campus pages are downloaded ONLY with --fetch.')
        print('Source directory:',a.source_dir)
        for url in SEEDS:print('SEED:',url)
        return
    sync(a.source_dir,a.max_pages,a.delay)
if __name__=='__main__':main()
