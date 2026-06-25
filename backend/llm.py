import json, re, httpx
from .config import BOOKS_DIR, SAVES_DIR
from .utils import (
    load_json, load_md, load_save_config, save_save_config,
    load_source_section, load_settings,
)


# ---- TOOL DEFINITIONS ----
TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "update_memo",
            "description": "更新备忘录，记录你认为重要的故事状态、角色关系、剧情线索等。备忘录会持续出现在后续的system prompt中，帮助你保持叙事一致性。请用中文撰写，尽可能简洁。",
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
            "description": "指定当前需要参考的原文小节ID列表。这些小节的原文内容会被加载到system prompt中供你参考。传入空数组则清除所有参考小节。",
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


def execute_tool_call(tool_call, book_id, save_id):
    """Execute a tool call and return the result string."""
    func_name = tool_call["function"]["name"]
    try:
        args = json.loads(tool_call["function"]["arguments"])
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON arguments"})

    if func_name == "update_memo":
        memo_text = args.get("memo_text", "")
        from .utils import save_md
        save_md(SAVES_DIR / save_id / "memo.md", memo_text)
        return json.dumps({"success": True, "message": "备忘录已更新"})

    elif func_name == "set_reference_sections":
        section_ids = args.get("section_ids", [])
        cfg = load_save_config(save_id)
        cfg["reference_sections"] = section_ids
        save_save_config(save_id, cfg)
        return json.dumps({"success": True, "message": f"已设置参考小节: {section_ids}"})

    return json.dumps({"error": f"Unknown function: {func_name}"})


# ---- LLM CLIENT ----
async def call_llm(messages, settings, tools=None):
    url = (settings.get("llm_base_url", "") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    key = settings.get("llm_api_key", "")
    model = settings.get("llm_model", "") or "gpt-4o"
    payload = {"model": model, "messages": messages, "temperature": 0.8, "max_tokens": 2048}
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
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
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
- `update_memo(memo_text)`
- `set_reference_sections(section_ids)`

## Strategy
- Default: skip tools, generate narrative JSON immediately. Quality > token waste.
- Only call tools when:
  - The story has clearly moved into a new scene/chapter needing different reference sections.
  - You've learned critical new plot/character information worth recording in the memo.
  - The player's action deviates from the original plot: consult the Story Index to determine if the deviation may intersect with characters, locations, or events not covered by the currently loaded reference sections. If so, call `set_reference_sections` to load those relevant sections before generating.

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
            parts.append("""
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
                        parts.append("\n(Reference truncated due to length limit)")
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


# ---- NARRATIVE GENERATION ----
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
        parts.append('\n## Accelerate\nFast-forward. Summarize transition under 200 words, jump to next key scene.')
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

