import sqlite3,tempfile,unittest
from pathlib import Path
from aux_core.knowledge import LocalKnowledgeBase

class KnowledgeTests(unittest.TestCase):
    def make_db(self,path:Path):
        db=sqlite3.connect(path)
        db.executescript('''
        CREATE TABLE documents(id INTEGER PRIMARY KEY,source_id TEXT UNIQUE,title TEXT,source_url TEXT,effective_date TEXT,sha256 TEXT);
        CREATE TABLE chunks(id INTEGER PRIMARY KEY,document_id INTEGER,chunk_index INTEGER,text TEXT);
        CREATE VIRTUAL TABLE chunks_fts USING fts5(text,title,source_id,source_url);
        ''')
        cur=db.execute("INSERT INTO documents(source_id,title,source_url,effective_date,sha256) VALUES(?,?,?,?,?)",('ttu.test','Test Tennessee Tech Source','https://www.tntech.edu/test','2026-09-29','x'));did=cur.lastrowid
        cur=db.execute("INSERT INTO chunks(document_id,chunk_index,text) VALUES(?,?,?)",(did,0,'The Golden Eagle Welcome Center is a Tennessee Tech resource for visitors.'));cid=cur.lastrowid
        db.execute("INSERT INTO chunks_fts(rowid,text,title,source_id,source_url) VALUES(?,?,?,?,?)",(cid,'The Golden Eagle Welcome Center is a Tennessee Tech resource for visitors.','Test Tennessee Tech Source','ttu.test','https://www.tntech.edu/test'));db.commit();db.close()
    def test_retrieve_and_format(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'runtime/kb.sqlite3';p.parent.mkdir();self.make_db(p)
            kb=LocalKnowledgeBase({'enabled':True,'database_path':'runtime/kb.sqlite3','top_k':3},root)
            hits=kb.retrieve('Where is the Golden Eagle welcome center?')
            self.assertTrue(hits);self.assertEqual(hits[0].source_id,'ttu.test')
            ctx=kb.format_context(hits);self.assertIn('LOCAL KNOWLEDGE BASE CONTEXT',ctx);self.assertIn('ttu.test',ctx)
    def test_missing_db_is_safe(self):
        with tempfile.TemporaryDirectory() as td:
            kb=LocalKnowledgeBase({'enabled':True,'database_path':'missing.sqlite3'},Path(td))
            self.assertEqual(kb.retrieve('anything'),[]);self.assertFalse(kb.status()['available'])

    def test_generic_visual_query_does_not_retrieve_campus_noise(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'runtime/kb.sqlite3';p.parent.mkdir();self.make_db(p)
            kb=LocalKnowledgeBase({'enabled':True,'database_path':'runtime/kb.sqlite3','top_k':3},root)
            self.assertEqual(kb.retrieve('what do you see?'),[])

if __name__=='__main__':unittest.main()
