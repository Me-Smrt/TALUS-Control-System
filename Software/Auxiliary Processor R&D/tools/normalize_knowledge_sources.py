"""Dry-run-first repair for an accidentally nested Tennessee Tech source archive.

No URLs are fetched. Existing source metadata and full source text are preserved.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]

def plan(root: Path):
    source = root/'knowledge'/'sources'
    nested = source/'knowledge'/'sources'
    if not nested.is_dir():
        return [], [f'No nested directory at {nested}. No changes required.']
    moves, warnings = [], []
    for current in sorted(nested.rglob('*')):
        if not current.is_file():
            continue
        rel = current.relative_to(nested)
        # A prior extraction may contain a generated SQLite DB. That is not
        # source material, so never move it into the curated source directory.
        if current.suffix.lower() in {'.sqlite3', '.db', '.pyc'} or 'runtime' in rel.parts:
            warnings.append(f'GENERATED DATA (leave for manual archive): {rel}')
            continue
        target = source/rel
        if target.exists():
            if hashlib.sha256(current.read_bytes()).digest() == hashlib.sha256(target.read_bytes()).digest():
                warnings.append(f'IDENTICAL (leave nested source untouched): {rel}')
            else:
                warnings.append(f'CONFLICT (manual review required): {rel}')
            continue
        moves.append((current, target))
    return moves, warnings

def main():
    p = argparse.ArgumentParser(description='Inspect/flatten nested knowledge sources. Dry run unless --apply.')
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--apply',action='store_true')
    args=p.parse_args(); moves,warnings=plan(args.root.resolve())
    for a,b in moves:
        print(('MOVE' if args.apply else 'WOULD MOVE'),a.relative_to(args.root),'->',b.relative_to(args.root))
        if args.apply:
            b.parent.mkdir(parents=True,exist_ok=True)
            shutil.move(str(a),str(b))
    for warning in warnings: print('REVIEW:',warning)
    print(f'{len(moves)} files {"moved" if args.apply else "eligible to move"}; {len(warnings)} warnings.')
    print('No databases, downloaded archives or conflicting files were deleted.')
if __name__ == '__main__':main()
