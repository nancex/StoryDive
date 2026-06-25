#!/usr/bin/env python3
"""split_chapter.py — split chX.txt by ===Split=== markers into chX_Y.txt in source/"""

import re
from pathlib import Path

SPLIT_MARKER = "===Split==="
BOOKS_ROOT = Path(__file__).resolve().parent.parent / "books"


def find_chapter_dirs(books_root: Path) -> list[Path]:
    results = []
    if not books_root.exists():
        return results
    for sub in sorted(books_root.iterdir()):
        if not sub.is_dir():
            continue
        ch_files = sorted(
            sub.glob("ch[0-9]*.txt"),
            key=lambda p: int(re.search(r"ch(\d+)", p.stem).group(1)),
        )
        if ch_files:
            results.append(sub)
    return results


def natural_sort_key(path: Path) -> int:
    m = re.search(r"ch(\d+)", path.stem)
    return int(m.group(1)) if m else 0


def split_one_chapter(ch_path: Path, source_dir: Path) -> int:
    text = ch_path.read_text(encoding="utf-8")
    parts = text.split(SPLIT_MARKER)
    m = re.search(r"ch(\d+)", ch_path.stem)
    ch_num = int(m.group(1)) if m else 0
    count = 0
    for part in parts:
        cleaned = part.strip()
        if not cleaned:
            continue
        out_path = source_dir / f"ch{ch_num}_{count + 1}.txt"
        out_path.write_text(cleaned, encoding="utf-8")
        lines = cleaned.count(chr(10)) + 1
        print(f"    -> {out_path.name}  ({len(cleaned)} chars, {lines} lines)")
        count += 1
    return count


def main():
    book_dirs = find_chapter_dirs(BOOKS_ROOT)
    if not book_dirs:
        print("No chX.txt files found in books/ subdirectories.")
        print("Run epub_split.py first.")
        return
    print("\nAvailable books:")
    print("-" * 50)
    for idx, d in enumerate(book_dirs, 1):
        ch_count = len(list(d.glob("ch[0-9]*.txt")))
        print(f"  [{idx}] {d.name}/  ({ch_count} chapters)")
    print("-" * 50)
    while True:
        try:
            choice = input("Enter number (q to quit): ").strip()
            if choice.lower() == "q":
                print("Quit.")
                return
            idx = int(choice) - 1
            if 0 <= idx < len(book_dirs):
                book_dir = book_dirs[idx]
                break
            print(f"Invalid, enter 1-{len(book_dirs)}")
        except (ValueError, EOFError):
            print("Invalid input.")
    print(f"\nSelected: {book_dir.name}/")
    source_dir = book_dir / "source"
    source_dir.mkdir(exist_ok=True)
    chapter_files = sorted(book_dir.glob("ch[0-9]*.txt"), key=natural_sort_key)
    total_sections = 0
    total_with_splits = 0
    for ch_file in chapter_files:
        text = ch_file.read_text(encoding="utf-8")
        marker_count = text.count(SPLIT_MARKER)
        print(f"  {ch_file.name}: {marker_count} split marker(s)")
        if marker_count > 0:
            total_with_splits += 1
        n = split_one_chapter(ch_file, source_dir)
        total_sections += n
    print(f"\nDone! {total_sections} sections written to {source_dir}/")
    if total_with_splits == 0:
        print("Tip: No ===Split=== markers found. Add them manually in chX.txt and retry.")

if __name__ == "__main__":
    main()
