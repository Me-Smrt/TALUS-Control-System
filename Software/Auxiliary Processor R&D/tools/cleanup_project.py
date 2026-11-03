"""Conservative cleanup of generated files and version-suffixed tests.

Default is a dry run. Does NOT touch models, databases, configs, telemetry,
recordings, Blender models, or knowledge source documents.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]

def planned_renames(tests: Path):
    files = sorted(tests.glob('test_*_v[0-9]*.py'))
    # Prefer semantic names for regression families with multiple revisions.
    semantic = {
        'test_aec_bargein_v060.py':'test_aec_bargein_core.py',
        'test_aec_bargein_v061.py':'test_aec_bargein_readiness.py',
        'test_aec_bargein_v062.py':'test_aec_bargein_buffering.py',
        'test_aec_bargein_v063.py':'test_aec_bargein_false_positives.py',
        'test_reasoning_v034.py':'test_reasoning_profiles.py',
        'test_reasoning_v037.py':'test_reasoning_technical.py',
        'test_engagement_v058.py':'test_engagement_direct_address.py',
        'test_conversation_reset_v033.py':'test_conversation_reset_extended.py',
    }
    reserved = {p.name for p in tests.glob('*.py') if p not in files}
    out = []
    for file in files:
        proposed = semantic.get(file.name) or re.sub(r'_v\d+(?=\.py$)', '', file.name)
        if proposed in reserved:
            # Preserve distinct coverage without versioned filenames.
            proposed = file.stem + '_regression.py'
            proposed = re.sub(r'_v\d+_regression', '_regression', proposed)
        if proposed in reserved:
            suffix = 2
            stem = Path(proposed).stem
            while f'{stem}_{suffix}.py' in reserved: suffix+=1
            proposed = f'{stem}_{suffix}.py'
        reserved.add(proposed)
        if proposed!=file.name: out.append((file, file.with_name(proposed)))
    return out

def main():
    ap=argparse.ArgumentParser(description='Dry-run-first AUX cleanup')
    ap.add_argument('--root',type=Path,default=ROOT)
    ap.add_argument('--apply',action='store_true')
    ap.add_argument('--rename-tests',action='store_true',help='Rename versioned test modules collision-safely')
    ap.add_argument('--archive-old',action='store_true',help='Move obsolete notes, backups and old source ZIP into _archive/ instead of deleting')
    a=ap.parse_args(); root=a.root.resolve()
    removable = [root/'tools'/'install_startup_cue.py']
    # Prune environments, model weights and saved data before walking; a
    # virtualenv can contain tens of thousands of unrelated package caches.
    for directory, children, files in os.walk(root):
        here = Path(directory)
        if here.name == '__pycache__':
            removable.append(here)
            children[:] = []
            continue
        children[:] = [x for x in children if x not in
                        {'.venv','venv','.git','models','runtime','knowledge','logs'}]
    removable += [root/'.pytest_cache']
    for path in removable:
        if path.exists():
            print(('DELETE' if a.apply else 'WOULD DELETE'),path.relative_to(root))
            if a.apply:
                if path.is_dir(): shutil.rmtree(path)
                else: path.unlink()
    if a.rename_tests:
        for old,new in planned_renames(root/'tests'):
            print(('RENAME' if a.apply else 'WOULD RENAME'),old.name,'->',new.name)
            if a.apply:old.rename(new)
    if a.archive_old:
        candidates = [root/'PATCH_NOTES.md', root/'PATCH_NOTES_STARTUP.md',
                      root/'main.py.before_startup_cue.bak']
        candidates += list(root.glob('Tennessee_Tech_Knowledge_Archive_*.zip'))
        archive = root/'_archive'/'previous_iterations'
        for old in candidates:
            if not old.exists():continue
            target = archive/old.name
            if target.exists():
                print('SKIP archive conflict:',old.name)
                continue
            print(('ARCHIVE' if a.apply else 'WOULD ARCHIVE'),old.name,'->',target.relative_to(root))
            if a.apply:
                archive.mkdir(parents=True,exist_ok=True)
                old.rename(target)
    print('Preserved all model assets, knowledge sources, databases, user state, and logs.')
if __name__ == '__main__': main()
