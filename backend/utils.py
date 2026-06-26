import json, re
from .config import BOOKS_DIR, SAVES_DIR

def load_json(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def load_md(p):
    return open(p, "r", encoding="utf-8").read() if p.exists() else ""

def load_txt(p):
    return open(p, "r", encoding="utf-8").read() if p.exists() else ""

def save_md(p, c):
    p.parent.mkdir(parents=True, exist_ok=True)
    open(p, "w", encoding="utf-8").write(c)

def parse_story_to_paragraphs(text):
    pars = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if ": " in line and not line.startswith("#") and not line.startswith("-"):
            parts = line.split(": ", 1)
            sp = parts[0].strip()
            if sp and len(sp) < 20 and not sp.startswith("http"):
                pars.append({"type": "dialogue", "speaker": sp, "text": parts[1].strip()})
                continue
        pars.append({"type": "narration", "text": line})
    return pars

def get_save_count(bid):
    n = 0
    if SAVES_DIR.exists():
        for sd in SAVES_DIR.iterdir():
            if sd.is_dir() and (sd / "config.json").exists():
                try:
                    if load_json(sd / "config.json").get("book_id") == bid:
                        n += 1
                except Exception:
                    pass
    return n

def get_saves_for_book(bid):
    r = []
    if SAVES_DIR.exists():
        for sd in SAVES_DIR.iterdir():
            if sd.is_dir() and (sd / "config.json").exists():
                try:
                    if load_json(sd / "config.json").get("book_id") == bid:
                        r.append(sd.name)
                except Exception:
                    pass
    return r

def load_save_config(save_id):
    p = SAVES_DIR / save_id / "config.json"
    return load_json(p) if p.exists() else {}

def save_save_config(save_id, cfg):
    p = SAVES_DIR / save_id / "config.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def load_source_section(book_id, section_id):
    """Load a source section file. Tries .md first, then .txt."""
    src_dir = BOOKS_DIR / book_id / "source"
    for ext in (".md", ".txt"):
        p = src_dir / (section_id + ext)
        if p.exists():
            return load_md(p)
    return None

def list_available_sections(book_id):
    """List all available source section IDs for a book."""
    src_dir = BOOKS_DIR / book_id / "source"
    if not src_dir.exists():
        return []
    sections = []
    for f in sorted(src_dir.iterdir(), key=lambda p: [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', p.stem)]):
        if f.suffix in (".md", ".txt"):
            sections.append(f.stem)
    return sections

def pars_to_story(pars):
    lines = []
    for p in pars:
        if p["type"] == "dialogue":
            lines.append(f"{p.get('speaker', '')}: {p['text']}")
        else:
            lines.append(p["text"])
    return "\n".join(lines)

def append_to_story(sid, pars):
    sp = SAVES_DIR / sid / "story.md"
    save_md(sp, load_md(sp).rstrip() + "\n" + pars_to_story(pars) + "\n")

def prune_story(sid, idx):
    sp = SAVES_DIR / sid / "story.md"
    lines = load_md(sp).strip().split("\n")
    if idx < len(lines):
        lines = lines[:idx]
    save_md(sp, "\n".join(lines) + ("\n" if lines else ""))

def load_settings():
    from .models import SettingsData
    sp = BOOKS_DIR.parent / "settings.json"
    return load_json(sp) if sp.exists() else SettingsData().model_dump()

