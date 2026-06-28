import json, re
from .config import BOOKS_DIR, SAVES_DIR

def load_json(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def load_md(p):
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def save_md(p, c):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(c)

def parse_story_to_paragraphs(text):
    pars = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if (": " in line or "： " in line or "：" in line) and not line.startswith("#") and not line.startswith("-"):
            parts = re.split(r"[:：]\s+", line, maxsplit=1) if re.search(r"[:：]\s+", line) else ["", ""]
            sp = parts[0].strip()
            if sp and len(sp) < 30 and not sp.startswith("http"):
                sp = re.sub(r"\s*[(（][^)）]*[)）]\s*$", "", sp).strip()
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
    """Return the active profile's settings dict."""
    from .models import SettingsData
    sp = BOOKS_DIR.parent / "settings.json"
    if not sp.exists():
        return SettingsData().model_dump()
    data = load_json(sp)
    # Auto-migrate old flat format to profiled format
    if "profiles" not in data:
        data = {"active_profile": "默认", "profiles": {"默认": data}}
        save_json(sp, data)
    active = data.get("active_profile", "默认")
    return data["profiles"].get(active, SettingsData().model_dump())

def load_all_settings():
    """Return the full settings dict (active_profile + profiles). Auto-migrates old format."""
    from .models import SettingsData
    sp = BOOKS_DIR.parent / "settings.json"
    if not sp.exists():
        return {"active_profile": "默认", "profiles": {"默认": SettingsData().model_dump()}}
    data = load_json(sp)
    if "profiles" not in data:
        data = {"active_profile": "默认", "profiles": {"默认": data}}
        save_json(sp, data)
    return data

def save_all_settings(data):
    """Save the full settings dict to disk."""
    sp = BOOKS_DIR.parent / "settings.json"
    save_json(sp, data)

def save_json(p, data):
    """Save a dict as JSON file."""
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)



