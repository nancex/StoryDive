import os, json, uuid, shutil, re, httpx
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
BOOKS_DIR = BASE_DIR / "books"
SAVES_DIR = BASE_DIR / "saves"

app = FastAPI(title="StoryDive API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class BookBrief(BaseModel):
    id: str; title: str; original_author: str; script_author: str
    genre: list; protagonist: str; save_count: int

class BookDetail(BaseModel):
    id: str; title: str; original_author: str; script_author: str
    upload_date: str; description: str; cover_image: str
    protagonist: str; genre: list; version: str

class SaveBrief(BaseModel):
    id: str; book_id: str; book_title: str
    last_modified: str; preview: list

class SaveDetail(BaseModel):
    id: str; book_id: str; book_title: str; book_author: str
    last_modified: str; story_preview: list; memo: str; reference_sections: list = []

class ActionRequest(BaseModel):
    save_id: str; action: str
    mode: str = "normal"
    target_paragraph_index: Optional[int] = None

class SettingsData(BaseModel):
    llm_base_url: str = ""; llm_api_key: str = ""; llm_model: str = ""
    image_base_url: str = ""; image_api_key: str = ""; image_model: str = ""
    tts_endpoint: str = ""; llm_timeout: int = 60; llm_debug: bool = False; llm_reasoning: bool = False

class MemoUpdateRequest(BaseModel):
    memo: str

class ReferenceUpdateRequest(BaseModel):
    sections: List[str]

def load_json(p):
    with open(p,"r",encoding="utf-8") as f: return json.load(f)
def load_md(p):
    return open(p,"r",encoding="utf-8").read() if p.exists() else ""
def load_txt(p):
    return open(p,"r",encoding="utf-8").read() if p.exists() else ""
def save_md(p, c):
    p.parent.mkdir(parents=True,exist_ok=True); open(p,"w",encoding="utf-8").write(c)

def load_settings():
    sp = BASE_DIR / "settings.json"
    return load_json(sp) if sp.exists() else SettingsData().model_dump()

def parse_story_to_paragraphs(text):
    pars = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line: continue
        if ": " in line and not line.startswith("#") and not line.startswith("-"):
            parts = line.split(": ",1)
            sp = parts[0].strip()
            if sp and len(sp)<20 and not sp.startswith("http"):
                pars.append({"type":"dialogue","speaker":sp,"text":parts[1].strip()})
                continue
        pars.append({"type":"narration","text":line})
    return pars

def get_save_count(bid):
    n=0
    if SAVES_DIR.exists():
        for sd in SAVES_DIR.iterdir():
            if sd.is_dir() and (sd/"config.json").exists():
                try:
                    if load_json(sd/"config.json").get("book_id")==bid: n+=1
                except: pass
    return n

def get_saves_for_book(bid):
    r=[]
    if SAVES_DIR.exists():
        for sd in SAVES_DIR.iterdir():
            if sd.is_dir() and (sd/"config.json").exists():
                try:
                    if load_json(sd/"config.json").get("book_id")==bid: r.append(sd.name)
                except: pass
    return r

def load_save_config(save_id):
    p = SAVES_DIR / save_id / "config.json"
    return load_json(p) if p.exists() else {}

def save_save_config(save_id, cfg):
    p = SAVES_DIR / save_id / "config.json"
    with open(p,"w",encoding="utf-8") as f: json.dump(cfg,f,ensure_ascii=False,indent=2)

# ---- LLM CLIENT ----
async def call_llm(messages, settings, tools=None):
    url = (settings.get("llm_base_url","") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    key = settings.get("llm_api_key","")
    model = settings.get("llm_model","") or "gpt-4o"
    payload = {"model":model,"messages":messages,"temperature":0.8,"max_tokens":2048}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    # DeepSeek reasoning support
    if model.lower().startswith("deepseek-") and settings.get("llm_reasoning", False):
        payload["reasoning_effort"] = "high"
        payload["extra_body"] = {"thinking": {"type": "enabled"}}
    debug = settings.get("llm_debug", False)
    if debug:
        print(f"\n=== LLM REQUEST ===\nURL: {url}\nModel: {model}\nPayload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n=== END REQUEST ===")
    headers = {"Authorization":f"Bearer {key}","Content-Type":"application/json"}
    to = settings.get("llm_timeout", 60) or 60
    async with httpx.AsyncClient(timeout=httpx.Timeout(float(to), connect=10.0)) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if debug:
            print(f"\n=== LLM RESPONSE ===\nStatus: {resp.status_code}\nBody:\n{json.dumps(data, ensure_ascii=False, indent=2)}\n=== END RESPONSE ===")
        # Token usage logging
        usage = data.get("usage", {})
        if usage:
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)
            cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
            cache_hit_rate = f"{(cached_tokens / prompt_tokens * 100):.1f}%" if prompt_tokens > 0 else "N/A"
            max_ctx = 131072
            if "32k" in model.lower() or "gpt-3.5" in model.lower():
                max_ctx = 32768
            ctx_pct = f"{(prompt_tokens / max_ctx * 100):.1f}%" if max_ctx > 0 else "N/A"
            print(f"[TOKEN] input={prompt_tokens} output={completion_tokens} total={total_tokens} "
                  f"cache_hit={cache_hit_rate} ctx_used={ctx_pct}")
        return data["choices"][0]["message"]

# ---- TOOL DEFINITIONS ----
TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "update_memo",
            "description": "更新备忘录，记录你认为重要的故事状态、角色关系、剧情线索等。备忘录会持续出现在后续的system prompt中，帮助你保持叙事一致性。请用中文撰写，保持简洁但有价值。",
            "parameters": {
                "type": "object",
                "properties": {
                    "memo_text": {
                        "type": "string",
                        "description": "更新后的完整备忘录文本（Markdown格式）"
                    }
                },
                "required": ["memo_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reference_sections",
            "description": "指定当前需要参考的原文小节ID列表。这些小节的原文内容会被加载到system prompt中供你参考。你可以在生成质量和token消耗之间做平衡——包含更多小节能提供更准确的原文背景，但会增加token消耗。建议偏向质量，适度包含必要的小节。传入空数组则清除所有参考小节。",
            "parameters": {
                "type": "object",
                "properties": {
                    "section_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "需要参考的原文小节ID列表，如 [\"ch1_1\", \"ch1_2\"]。传入 [] 清除所有参考。"
                    }
                },
                "required": ["section_ids"]
            }
        }
    }
]

def get_tool_defs():
    return TOOL_DEFS

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
    for f in sorted(src_dir.iterdir()):
        if f.suffix in (".md", ".txt"):
            sections.append(f.stem)
    return sections

def execute_tool_call(tool_call, book_id, save_id):
    """Execute a tool call and return the result string."""
    func_name = tool_call["function"]["name"]
    try:
        args = json.loads(tool_call["function"]["arguments"])
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON arguments"})

    if func_name == "update_memo":
        memo_text = args.get("memo_text", "")
        save_md(SAVES_DIR / save_id / "memo.md", memo_text)
        return json.dumps({"success": True, "message": "备忘录已更新"})

    elif func_name == "set_reference_sections":
        section_ids = args.get("section_ids", [])
        cfg = load_save_config(save_id)
        cfg["reference_sections"] = section_ids
        save_save_config(save_id, cfg)
        return json.dumps({"success": True, "message": f"已设置参考小节: {section_ids}"})

    return json.dumps({"error": f"Unknown function: {func_name}"})

# ---- SYSTEM PROMPT BUILDER ----
def build_system_prompt(book_id, save_id=None):
    setting = load_md(BOOKS_DIR / book_id / "setting.md")
    cfg = load_json(BOOKS_DIR / book_id / "config.json")
    parts = ["You are StoryDive' narrative engine for " + cfg["title"] + "."]

    # Core rules
    parts.append(f"""
## Core Rules
1. Return ONLY a JSON array. Each element is a narrative paragraph.
2. Fields: "type" ("narration" or "dialogue"), "text".
   For dialogue also include: "speaker", "expression" (neutral/happy/sad/angry/surprised/determined/nervous/scared/calm/confused/shocked/weary/laughing/embarrassed/smug/worried/grinning/suspicious).
3. Use third-person limited POV following the protagonist.
4. Generate 4-8 paragraphs. Last paragraph must be a natural break point for player input.
5. Maintain the original work's language style.

## Tools Available
You have access to the following tools. You may call them BEFORE generating the narrative to manage context:
- `update_memo(memo_text)`: Update the memo with important story state, character relationships, plot clues. The memo persists across calls to help you maintain consistency. Write in Chinese, be concise but valuable.
- `set_reference_sections(section_ids)`: Set which source sections to include as reference. Pass an array of section IDs like ["ch1_1", "ch1_2"]. Pass [] to clear all. Balance quality vs token usage - more sections = better accuracy but higher token cost. **Bias toward quality**: include sections likely relevant to the current scene.

## Strategy
- If reference sections are NOT yet loaded (see above), call `set_reference_sections` first to pick relevant sections.
- Once reference sections are set, generate the narrative JSON directly. Only call tools when:
  - The story has clearly moved into a new scene/chapter needing different reference sections.
  - You've learned critical new plot/character information worth recording in the memo.
- Default: skip tools, generate narrative JSON immediately. Quality > token waste.

## Setting
{setting}
""")

    # Index
    index = load_md(BOOKS_DIR / book_id / "index.md")
    if index.strip():
        parts.append(f"""
## Story Index (Chapter Outline)
{index}
""")

    # Memo & References (save-specific)
    if save_id:
        memo = load_md(SAVES_DIR / save_id / "memo.md")
        if memo.strip():
            # Limit memo to avoid overwhelming the prompt
            memo_display = memo[:2000] if len(memo) > 2000 else memo
            parts.append(f"""
## Current Memo
{memo_display}
""")

        scfg = load_save_config(save_id)
        ref_sections = scfg.get("reference_sections", [])
        if ref_sections:
            parts.append(f"""
## Reference Source Sections
The following sections from the original work are loaded for your reference:
""")
            total_ref_chars = 0
            max_ref_chars = 8000
            for sec_id in ref_sections:
                content = load_source_section(book_id, sec_id)
                if content:
                    remaining = max_ref_chars - total_ref_chars
                    if remaining <= 0:
                        parts.append(f"\n(Reference truncated due to length limit)")
                        break
                    if len(content) > remaining:
                        content = content[:remaining] + "\n...(truncated)"
                    parts.append(f"\n### {sec_id}\n{content}")
                    total_ref_chars += len(content)
                else:
                    parts.append(f"\n### {sec_id}\n(Section not found)")
        else:
            parts.append("""
## Reference Source Sections
No reference sections are currently loaded. You may call `set_reference_sections` to load relevant source material before generating.
""")

    parts.append("\nReturn ONLY the JSON array. No other text.")
    return "\n".join(parts)


async def generate_narrative(book_id, save_id, action=None, mode="normal"):
    settings = load_settings()
    if not settings.get("llm_api_key") or settings["llm_api_key"] == "sk-placeholder":
        raise RuntimeError("请先在设置中配置 LLM API Key")

    cfg = load_json(BOOKS_DIR / book_id / "config.json")
    story = load_md(SAVES_DIR / save_id / "story.md")
    protagonist = cfg.get("protagonist", "protagonist")

    sp = build_system_prompt(book_id, save_id)
    parts = [f'# Script: {cfg["title"]}', f'# Protagonist: {protagonist}']
    if mode == "speak":
        parts.append(f'\n## Player Action\n[{protagonist}] said: "{action}"\nGenerate story based on this dialogue.')
    elif mode == "accelerate":
        parts.append(f'\n## Accelerate\nFast-forward. Summarize transition under 200 words, jump to next key scene.')
    elif action:
        parts.append(f'\n## Player Action\n{action}\nGenerate story based on this.')
    else:
        parts.append('\n## Begin\nStart the story from the beginning.')

    story_snip = story[-2000:] if len(story) > 2000 else story
    parts.append(f'\n## Current Story (tail)\n{story_snip}')

    messages = [
        {"role": "system", "content": sp},
        {"role": "user", "content": "\n".join(parts)}
    ]

    max_tool_rounds = 3
    for round_num in range(max_tool_rounds):
        resp_msg = await call_llm(messages, settings, tools=get_tool_defs())

        tool_calls = resp_msg.get("tool_calls")
        if tool_calls:
            messages.append({"role": "assistant", "content": resp_msg.get("content"), "tool_calls": tool_calls})
            for tc in tool_calls:
                tool_result = execute_tool_call(tc, book_id, save_id)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})
            messages[0]["content"] = build_system_prompt(book_id, save_id)
            continue

        # No more tool calls - parse narrative
        content_text = resp_msg.get("content", "")
        result = parse_narrative_response(content_text)
        if result:
            return result
        # If parsing failed and we still have rounds, retry with a corrective message
        if round_num < max_tool_rounds - 1:
            messages.append({"role": "assistant", "content": content_text})
            messages.append({"role": "user", "content": "You did NOT return a JSON array. Please re-read the instructions and return ONLY a valid JSON array of narrative paragraphs. Each element must have \"type\" and \"text\" fields."})
            continue
        raise RuntimeError("LLM 连续多次未返回有效的 JSON 数组，请重试")

    raise RuntimeError("LLM 未返回有效的 JSON 数组")

def parse_narrative_response(content_text):
    """Parse LLM response into narrative paragraphs. Handles JSON arrays and plain text fallback."""
    if not content_text or not content_text.strip():
        return None

    # Try 1: Extract JSON array from response
    m = re.search(r'\[[\s\S]*?\](?=\s*$)', content_text)
    if not m:
        m = re.search(r'\[[\s\S]*\]', content_text)
    if m:
        try:
            raw = json.loads(m.group())
            if isinstance(raw, list):
                result = []
                for p in raw:
                    if not isinstance(p, dict):
                        continue
                    item = {"type": p.get("type", "narration"), "text": str(p.get("text", ""))}
                    if item["type"] == "dialogue":
                        item["speaker"] = p.get("speaker", "")
                        item["expression"] = p.get("expression", "neutral")
                    result.append(item)
                if result:
                    return result
        except (json.JSONDecodeError, TypeError):
            pass

    # Try 2: Treat as plain text - split by double newlines into narration paragraphs
    paragraphs = [p.strip() for p in content_text.split("\n\n") if p.strip()]
    if paragraphs and len(paragraphs) >= 2:
        result = []
        for p in paragraphs:
            # Clean up any markdown or numbering
            p = re.sub(r'^\d+[\.\)、]\s*', '', p)
            p = re.sub(r'^[-\*]\s*', '', p)
            result.append({"type": "narration", "text": p})
        return result

    # Try 3: Single paragraph - wrap it
    if len(content_text.strip()) > 20:
        return [{"type": "narration", "text": content_text.strip()}]

    return None


    cfg = load_json(BOOKS_DIR / book_id / "config.json")
    p = cfg.get("protagonist", "protagonist")
    if mode == "speak":
        return [{"type":"dialogue","speaker":p,"expression":"determined","text":action},
                {"type":"narration","text":f"{p}的话语在空气中回荡。"},
                {"type":"dialogue","speaker":"旁白","expression":"neutral","text":"（你说出了心中的话。接下来会怎样？）"}]
    elif mode == "regret":
        return [{"type":"narration","text":f"时间仿佛倒流了。{p}感到一阵晕眩。"},
                {"type":"narration","text":"世界线重新编织。这一次，一切将会不同。"},
                {"type":"dialogue","speaker":"旁白","expression":"neutral","text":"（你改变了历史的走向。）"}]
    elif mode == "accelerate":
        return [{"type":"narration","text":"时光如白驹过隙。命运的齿轮加速转动。"},
                {"type":"narration","text":f"当{p}再次意识到身在何处时，一切都已经不同了。"},
                {"type":"dialogue","speaker":"旁白","expression":"neutral","text":"（剧情已加速推进到下一个关键节点。）"}]
    elif action:
        return [{"type":"narration","text":f"你决定：{action}。这个选择让故事掀开了新的篇章。"},
                {"type":"narration","text":"周围的氛围随之改变。"},
                {"type":"dialogue","speaker":"旁白","text":f"{p}，你的旅程还在继续。"}]
    return [{"type":"narration","text":f"欢迎，{p}。你的故事即将开始。"},
            {"type":"narration","text":"在这个世界里，每一个选择都可能改变命运。"},
            {"type":"dialogue","speaker":"旁白","text":"准备好了吗？让我们开始吧。"}]

def pars_to_story(pars):
    lines = []
    for p in pars:
        if p["type"] == "dialogue": lines.append(f"{p.get('speaker','')}: {p['text']}")
        else: lines.append(p["text"])
    return "\n".join(lines)

def append_to_story(sid, pars):
    sp = SAVES_DIR / sid / "story.md"
    save_md(sp, load_md(sp).rstrip() + "\n" + pars_to_story(pars) + "\n")

def prune_story(sid, idx):
    sp = SAVES_DIR / sid / "story.md"
    lines = load_md(sp).strip().split("\n")
    if idx < len(lines): lines = lines[:idx]
    save_md(sp, "\n".join(lines) + ("\n" if lines else ""))

# ---- API ----
@app.get("/api/books")
def list_books():
    books = []
    if BOOKS_DIR.exists():
        for bd in BOOKS_DIR.iterdir():
            if bd.is_dir() and (bd / "config.json").exists():
                d = load_json(bd / "config.json")
                books.append(BookBrief(id=d["id"],title=d["title"],original_author=d["original_author"],
                    script_author=d["script_author"],genre=d.get("genre",[]),
                    protagonist=d.get("protagonist",""),save_count=get_save_count(d["id"])))
    return {"books": [b.model_dump() for b in books]}

@app.get("/api/books/{book_id}")
def get_book(book_id: str):
    c = BOOKS_DIR / book_id / "config.json"
    if not c.exists(): raise HTTPException(404)
    d = load_json(c)
    return BookDetail(id=d["id"],title=d["title"],original_author=d["original_author"],
        script_author=d["script_author"],upload_date=d.get("upload_date",""),
        description=d.get("description",""),cover_image=d.get("cover_image",""),
        protagonist=d.get("protagonist",""),genre=d.get("genre",[]),
        version=d.get("version","")).model_dump()

@app.get("/api/saves")
def list_saves():
    saves = []
    if SAVES_DIR.exists():
        for sd in SAVES_DIR.iterdir():
            if sd.is_dir() and (sd / "config.json").exists() and (sd / "story.md").exists():
                d = load_json(sd / "config.json")
                st = load_md(sd / "story.md")
                pars = parse_story_to_paragraphs(st)
                preview = pars[-3:] if len(pars) > 3 else pars
                saves.append(SaveBrief(id=sd.name,book_id=d.get("book_id",""),
                    book_title=d.get("book_title",""),
                    last_modified=datetime.fromtimestamp((sd/"story.md").stat().st_mtime).isoformat(),
                    preview=[p["text"][:80] for p in preview]))
    return {"saves": [s.model_dump() for s in saves]}

@app.get("/api/saves/{save_id}")
def get_save(save_id: str):
    sd = SAVES_DIR / save_id
    if not sd.exists(): raise HTTPException(404)
    d = load_json(sd / "config.json") if (sd / "config.json").exists() else {}
    st = load_md(sd / "story.md"); mem = load_md(sd / "memo.md")
    pars = parse_story_to_paragraphs(st)
    preview = pars[-6:] if len(pars) > 6 else pars
    return SaveDetail(id=save_id,book_id=d.get("book_id",""),book_title=d.get("book_title",""),
        book_author=d.get("book_author",""),
        last_modified=datetime.fromtimestamp((sd/"story.md").stat().st_mtime).isoformat() if (sd/"story.md").exists() else "",
        story_preview=[{"type":p["type"],"speaker":p.get("speaker"),"text":p["text"][:100]} for p in preview],
        memo=mem,reference_sections=d.get("reference_sections",[])).model_dump()

@app.post("/api/books/{book_id}/start")
async def start_book(book_id: str):
    c = BOOKS_DIR / book_id / "config.json"
    if not c.exists(): raise HTTPException(404)
    d = load_json(c)
    sid = f"save_{uuid.uuid4().hex[:12]}"
    sd = SAVES_DIR / sid; sd.mkdir(parents=True, exist_ok=True)
    scfg = {"book_id": book_id, "book_title": d["title"], "book_author": d.get("original_author",""),
            "protagonist": d.get("protagonist",""), "created": datetime.now().isoformat(),
            "reference_sections": []}
    with open(sd / "config.json", "w", encoding="utf-8") as f: json.dump(scfg, f, ensure_ascii=False, indent=2)
    save_md(sd / "story.md", f"# {d['title']}\n\n")
    save_md(sd / "memo.md", f"# 备忘录\n\n游戏刚开始。\n")
    try:
        queue = await generate_narrative(book_id, sid)
        append_to_story(sid, queue)
        return {"save_id": sid, "book_title": d["title"], "paragraph_queue": queue,
                "memo": load_md(sd / "memo.md"),
                "reference_sections": load_save_config(sid).get("reference_sections", []),
                "existing_saves": get_saves_for_book(book_id)}
    except Exception as e:
        import traceback; traceback.print_exc()
        shutil.rmtree(str(sd))
        raise HTTPException(500, f"生成初始剧情失败：{str(e)}")

@app.post("/api/saves/{save_id}/continue")
async def continue_save(save_id: str):
    sd = SAVES_DIR / save_id
    if not sd.exists(): raise HTTPException(404)
    cfg = load_json(sd / "config.json")
    full_history = parse_story_to_paragraphs(load_md(sd / "story.md"))
    if len(full_history) == 0:
        full_history = [{"type":"narration","text":"[Empty story]"}]
    return {"save_id": save_id, "book_id": cfg["book_id"], "book_title": cfg["book_title"], "full_history": full_history,
            "memo": load_md(sd / "memo.md"),
            "reference_sections": cfg.get("reference_sections", [])}

@app.post("/api/game/action")
async def submit_action(req: ActionRequest):
    try:
        sd = SAVES_DIR / req.save_id
        if not sd.exists(): raise HTTPException(404)
        cfg = load_json(sd / "config.json")
        bid = cfg["book_id"]
        if req.mode == "regret":
            prune_story(req.save_id, req.target_paragraph_index or 0)
        queue = await generate_narrative(bid, req.save_id, req.action, req.mode)
        if req.mode != "regret":
            append_to_story(req.save_id, queue)
        settings = load_settings(); is_mock = not settings.get("llm_api_key") or settings["llm_api_key"] == "sk-placeholder"
        return {"paragraph_queue": queue, "mode": req.mode, "mock": is_mock}
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"error": str(e), "paragraph_queue": [], "mock": False}

# ---- MEMO & REFERENCE API ----
@app.post("/api/saves/{save_id}/memo")
def update_memo(save_id: str, req: MemoUpdateRequest):
    sd = SAVES_DIR / save_id
    if not sd.exists(): raise HTTPException(404)
    save_md(sd / "memo.md", req.memo)
    return {"status": "ok", "memo": req.memo}

@app.post("/api/saves/{save_id}/reference")
def update_reference(save_id: str, req: ReferenceUpdateRequest):
    sd = SAVES_DIR / save_id
    if not sd.exists(): raise HTTPException(404)
    cfg = load_save_config(save_id)
    cfg["reference_sections"] = req.sections
    save_save_config(save_id, cfg)
    return {"status": "ok", "reference_sections": req.sections}

@app.get("/api/books/{book_id}/sections")
def list_book_sections(book_id: str):
    """List all available source sections for a book."""
    return {"sections": list_available_sections(book_id)}

@app.get("/api/settings")
def get_settings():
    return load_settings()

@app.post("/api/settings")
def save_settings(data: SettingsData):
    sp = BASE_DIR / "settings.json"
    with open(sp, "w", encoding="utf-8") as f: json.dump(data.model_dump(), f, ensure_ascii=False, indent=2)
    return {"status": "ok"}

@app.delete("/api/saves/{save_id}")
def delete_save(save_id: str):
    sd = SAVES_DIR / save_id
    if not sd.exists(): raise HTTPException(404)
    shutil.rmtree(sd)
    return {"status": "deleted"}

@app.get("/api/books/{book_id}/index")
def get_book_index(book_id: str):
    idx = BOOKS_DIR / book_id / "index.md"
    if not idx.exists(): raise HTTPException(404)
    return {"content": load_md(idx)}

if __name__ == "__main__":
    import uvicorn, logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    log_config = {
        "version": 1, "disable_existing_loggers": False,
        "formatters": {"plain": {"format": "%(asctime)s [%(levelname)s] %(message)s", "datefmt": "%H:%M:%S"}},
        "handlers": {"plain": {"class": "logging.StreamHandler", "formatter": "plain"}},
        "loggers": {"uvicorn": {"handlers": ["plain"], "level": "INFO"}, "uvicorn.access": {"handlers": ["plain"], "level": "INFO"}},
    }
    uvicorn.run(app, host="0.0.0.0", port=8800, log_config=log_config)



