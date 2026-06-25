import json, uuid, shutil
from datetime import datetime
from fastapi import APIRouter, HTTPException
from .config import BOOKS_DIR, SAVES_DIR
from .models import (
    BookBrief, BookDetail, SaveBrief, SaveDetail,
    ActionRequest, SettingsData, MemoUpdateRequest, ReferenceUpdateRequest,
)
from .utils import (
    load_json, load_md, save_md, parse_story_to_paragraphs,
    get_save_count, get_saves_for_book, load_save_config, save_save_config,
    pars_to_story, append_to_story, prune_story, load_settings,
    list_available_sections,
)
from .llm import generate_narrative

router = APIRouter(prefix="/api")


# ---- BOOKS ----
@router.get("/books")
def list_books():
    books = []
    if BOOKS_DIR.exists():
        for bd in BOOKS_DIR.iterdir():
            if bd.is_dir() and (bd / "config.json").exists():
                d = load_json(bd / "config.json")
                books.append(BookBrief(
                    id=d["id"], title=d["title"],
                    original_author=d["original_author"],
                    script_author=d["script_author"],
                    genre=d.get("genre", []),
                    protagonist=d.get("protagonist", ""),
                    save_count=get_save_count(d["id"]),
                ))
    return {"books": [b.model_dump() for b in books]}


@router.get("/books/{book_id}")
def get_book(book_id: str):
    c = BOOKS_DIR / book_id / "config.json"
    if not c.exists():
        raise HTTPException(404)
    d = load_json(c)
    return BookDetail(
        id=d["id"], title=d["title"],
        original_author=d["original_author"],
        script_author=d["script_author"],
        upload_date=d.get("upload_date", ""),
        description=d.get("description", ""),
        cover_image=d.get("cover_image", ""),
        protagonist=d.get("protagonist", ""),
        genre=d.get("genre", []),
        version=d.get("version", ""),
    ).model_dump()


@router.get("/books/{book_id}/index")
def get_book_index(book_id: str):
    idx = BOOKS_DIR / book_id / "index.md"
    if not idx.exists():
        raise HTTPException(404)
    return {"content": load_md(idx)}


@router.get("/books/{book_id}/sections")
def list_book_sections(book_id: str):
    """List all available source sections for a book."""
    return {"sections": list_available_sections(book_id)}


@router.post("/books/{book_id}/start")
async def start_book(book_id: str):
    c = BOOKS_DIR / book_id / "config.json"
    if not c.exists():
        raise HTTPException(404)
    d = load_json(c)
    sid = f"save_{uuid.uuid4().hex[:12]}"
    sd = SAVES_DIR / sid
    sd.mkdir(parents=True, exist_ok=True)
    scfg = {
        "book_id": book_id,
        "book_title": d["title"],
        "book_author": d.get("original_author", ""),
        "protagonist": d.get("protagonist", ""),
        "created": datetime.now().isoformat(),
        "reference_sections": [],
    }
    with open(sd / "config.json", "w", encoding="utf-8") as f:
        json.dump(scfg, f, ensure_ascii=False, indent=2)
    save_md(sd / "story.md", f"# {d['title']}\n\n")
    save_md(sd / "memo.md", "# 备忘录\n\n游戏刚开始。\n")
    try:
        queue = await generate_narrative(book_id, sid)
        append_to_story(sid, queue)
        return {
            "save_id": sid,
            "book_title": d["title"],
            "paragraph_queue": queue,
            "memo": load_md(sd / "memo.md"),
            "reference_sections": load_save_config(sid).get("reference_sections", []),
            "existing_saves": get_saves_for_book(book_id),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        shutil.rmtree(str(sd))
        raise HTTPException(500, f"生成初始剧情失败：{str(e)}")


# ---- SAVES ----
@router.get("/saves")
def list_saves():
    saves = []
    if SAVES_DIR.exists():
        for sd in SAVES_DIR.iterdir():
            if sd.is_dir() and (sd / "config.json").exists() and (sd / "story.md").exists():
                d = load_json(sd / "config.json")
                st = load_md(sd / "story.md")
                pars = parse_story_to_paragraphs(st)
                preview = pars[-3:] if len(pars) > 3 else pars
                saves.append(SaveBrief(
                    id=sd.name,
                    book_id=d.get("book_id", ""),
                    book_title=d.get("book_title", ""),
                    last_modified=datetime.fromtimestamp((sd / "story.md").stat().st_mtime).isoformat(),
                    preview=[p["text"][:80] for p in preview],
                ))
    return {"saves": [s.model_dump() for s in saves]}


@router.get("/saves/{save_id}")
def get_save(save_id: str):
    sd = SAVES_DIR / save_id
    if not sd.exists():
        raise HTTPException(404)
    d = load_json(sd / "config.json") if (sd / "config.json").exists() else {}
    st = load_md(sd / "story.md")
    mem = load_md(sd / "memo.md")
    pars = parse_story_to_paragraphs(st)
    preview = pars[-6:] if len(pars) > 6 else pars
    return SaveDetail(
        id=save_id,
        book_id=d.get("book_id", ""),
        book_title=d.get("book_title", ""),
        book_author=d.get("book_author", ""),
        last_modified=datetime.fromtimestamp((sd / "story.md").stat().st_mtime).isoformat(),
        story_preview=preview,
        memo=mem,
        reference_sections=d.get("reference_sections", []),
    ).model_dump()


@router.delete("/saves/{save_id}")
def delete_save(save_id: str):
    sd = SAVES_DIR / save_id
    if not sd.exists():
        raise HTTPException(404)
    shutil.rmtree(sd)
    return {"status": "deleted"}


@router.post("/saves/{save_id}/continue")
async def continue_save(save_id: str):
    sd = SAVES_DIR / save_id
    if not sd.exists():
        raise HTTPException(404)
    cfg = load_json(sd / "config.json")
    full_history = parse_story_to_paragraphs(load_md(sd / "story.md"))
    if len(full_history) == 0:
        full_history = [{"type": "narration", "text": "[Empty story]"}]
    return {
        "save_id": save_id,
        "book_id": cfg["book_id"],
        "book_title": cfg["book_title"],
        "full_history": full_history,
        "memo": load_md(sd / "memo.md"),
        "reference_sections": cfg.get("reference_sections", []),
    }


# ---- GAME ----
@router.post("/game/action")
async def submit_action(req: ActionRequest):
    try:
        sd = SAVES_DIR / req.save_id
        if not sd.exists():
            raise HTTPException(404)
        cfg = load_json(sd / "config.json")
        bid = cfg["book_id"]
        if req.mode == "regret":
            prune_story(req.save_id, req.target_paragraph_index or 0)
        queue = await generate_narrative(bid, req.save_id, req.action, req.mode)
        if req.mode != "regret":
            append_to_story(req.save_id, queue)
        settings = load_settings()
        is_mock = not settings.get("llm_api_key") or settings["llm_api_key"] == "sk-placeholder"
        return {"paragraph_queue": queue, "mode": req.mode, "mock": is_mock}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e), "paragraph_queue": [], "mock": False}


# ---- MEMO & REFERENCE ----
@router.post("/saves/{save_id}/memo")
def update_memo(save_id: str, req: MemoUpdateRequest):
    sd = SAVES_DIR / save_id
    if not sd.exists():
        raise HTTPException(404)
    save_md(sd / "memo.md", req.memo)
    return {"status": "ok", "memo": req.memo}


@router.post("/saves/{save_id}/reference")
def update_reference(save_id: str, req: ReferenceUpdateRequest):
    sd = SAVES_DIR / save_id
    if not sd.exists():
        raise HTTPException(404)
    cfg = load_save_config(save_id)
    cfg["reference_sections"] = req.sections
    save_save_config(save_id, cfg)
    return {"status": "ok", "reference_sections": req.sections}


# ---- SETTINGS ----
@router.get("/settings")
def get_settings():
    return load_settings()


@router.post("/settings")
def save_settings(data: SettingsData):
    from .config import BASE_DIR
    sp = BASE_DIR / "settings.json"
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(data.model_dump(), f, ensure_ascii=False, indent=2)
    return {"status": "ok"}
