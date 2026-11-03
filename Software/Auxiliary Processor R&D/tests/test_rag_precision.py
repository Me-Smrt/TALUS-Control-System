import sqlite3
from pathlib import Path

from aux_core.knowledge import LocalKnowledgeBase


def build_db(path: Path):
    db = sqlite3.connect(path)
    db.executescript('''
    CREATE TABLE documents(id INTEGER PRIMARY KEY,source_id TEXT UNIQUE,title TEXT,source_url TEXT,effective_date TEXT,sha256 TEXT);
    CREATE TABLE chunks(id INTEGER PRIMARY KEY,document_id INTEGER,chunk_index INTEGER,text TEXT);
    CREATE VIRTUAL TABLE chunks_fts USING fts5(text,title,source_id,source_url);
    ''')
    docs = [
        ("ttu.dining", "Dining Services", "Dining locations provide meals and hot food for students on campus."),
        ("ttu.financialaid.coa", "Cost of Attendance", "The student cost of attendance estimate includes food and housing expenses."),
    ]
    for source_id, title, text in docs:
        cur = db.execute("INSERT INTO documents(source_id,title,source_url,effective_date,sha256) VALUES(?,?,?,?,?)", (source_id,title,"https://example.test",None,"x"))
        did = cur.lastrowid
        cur = db.execute("INSERT INTO chunks(document_id,chunk_index,text) VALUES(?,?,?)", (did,0,text))
        cid = cur.lastrowid
        db.execute("INSERT INTO chunks_fts(rowid,text,title,source_id,source_url) VALUES(?,?,?,?,?)", (cid,text,title,source_id,"https://example.test"))
    db.commit(); db.close()


def test_dining_query_prefers_dining_and_drops_coa_noise(tmp_path: Path):
    p = tmp_path / "runtime/kb.sqlite3"; p.parent.mkdir(); build_db(p)
    kb = LocalKnowledgeBase({"enabled":True,"database_path":"runtime/kb.sqlite3","top_k":5}, tmp_path)
    hits = kb.retrieve("Where can I get food on campus?")
    assert hits
    assert hits[0].source_id == "ttu.dining"
    assert all("financialaid" not in h.source_id for h in hits)
    diag = kb.query_diagnostics("Where can I get food on campus?")
    assert diag["attempted"] is True
    assert "dining" in diag["intents"]


def test_general_food_question_does_not_pull_campus_rag(tmp_path: Path):
    p = tmp_path / "runtime/kb.sqlite3"; p.parent.mkdir(); build_db(p)
    kb = LocalKnowledgeBase({"enabled":True,"database_path":"runtime/kb.sqlite3"}, tmp_path)
    assert kb.retrieve("What food has the most protein?") == []
