import re
from pathlib import Path

BOOK_DIR = Path(r"F:\.workspace\StoryDive\books\re_zero")

chapter_files = sorted(
    BOOK_DIR.glob("ch[0-9]*.txt"),
    key=lambda p: int(re.search(r"ch(\d+)", p.stem).group(1)),
)

for ch_file in chapter_files:
    lines = ch_file.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Subsection marker: number-only line followed by empty line
        # Skip "1" — first subsection doesn't need a split marker
        if (re.match(r"^\d+$", stripped) and
                stripped != "1" and
                i + 1 < len(lines) and
                lines[i + 1].strip() == ""):
            new_lines.append("===Split===\n")
        new_lines.append(line)

    ch_file.write_text("".join(new_lines), encoding="utf-8")
    marker_count = "".join(new_lines).count("===Split===")
    print(f"  {ch_file.name}: added {marker_count} markers")

print("Done")
