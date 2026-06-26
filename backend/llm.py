import json, re, httpx, sys, os
from .config import BOOKS_DIR, SAVES_DIR
from .utils import (
    load_json, load_md, save_md, load_save_config, save_save_config,
    load_source_section, load_settings,
)

# ── LLM generation parameters ──
LLM_TEMPERATURE = 0.5
LLM_MAX_TOKENS = 2048

# ── Truncation / generation constants ──
STORY_TAIL_CHARS = 16000        # chars from story tail to include in user prompt
MEMO_MAX_CHARS = 2000          # max chars of memo in system prompt
COMPREHENSION_MAX_CHARS = 8000 # max chars of comprehension summary
REFERENCE_MAX_CHARS = 16000     # max total chars of reference sections
SPEAKER_MAX_LEN = 30           # max speaker name length in dialogue parsing
MIN_CONTENT_LEN = 20           # min content length for fallback parsing
MAX_TOOL_ROUNDS = 3            # max tool-calling rounds in generate_narrative
DEFAULT_TIMEOUT = 60           # default LLM request timeout (seconds)
CONNECT_TIMEOUT = 10.0         # connection timeout (seconds)

# ── Debug output helper (raw fd write to stderr, un-bufferable) ──
def _debug_print(msg: str):
    '''Write directly to stderr file descriptor, bypassing all Python io buffering and uvicorn capture.'''
    try:
        os.write(2, (msg + "\n").encode("utf-8"))
    except Exception:
        pass

def _sanitize_payload_for_debug(payload):
    """Return a copy of payload with lengthy sections in system prompts replaced by character counts."""
    import copy, re
    sp = copy.deepcopy(payload)
    section_pattern = re.compile(
        r'(## (?:Story Comprehension|Setting|Story Index|Reference Source Sections|Core Rules|Narrative Quality|Tools Available|Strategy)\n)(.*?)(?=\n## (?:Setting|Story Index|Reference Source Sections|Core Rules|Narrative Quality|Tools Available|Strategy)|$)',
        re.DOTALL
    )
    for msg in sp.get("messages", []):
        content = msg.get("content", "")
        if isinstance(content, str):
            def replacer(m):
                return m.group(1) + f"({len(m.group(2))} characters)"
            msg["content"] = section_pattern.sub(replacer, content)
    return sp
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



def execute_tool_call(tool_call, book_id, save_id):
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

# ---- LLM CLIENT (non-streaming) ----
async def call_llm(messages, settings, tools=None):
    url = (settings.get("llm_base_url", "") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    key = settings.get("llm_api_key", "")
    model = settings.get("llm_model", "") or "gpt-4o"
    payload = {"model": model, "messages": messages, "temperature": LLM_TEMPERATURE, "max_tokens": LLM_MAX_TOKENS}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    extra_body_str = settings.get("llm_extra_body", "")
    if extra_body_str and extra_body_str.strip():
        try:
            extra_body = json.loads(extra_body_str)
            payload["extra_body"] = extra_body
        except json.JSONDecodeError:
            pass
    debug = settings.get("llm_debug", False)
    if debug:
        _debug_print(f"\n=== LLM REQUEST ===\nURL: {url}\nModel: {model}\nPayload:\n{json.dumps(_sanitize_payload_for_debug(payload), ensure_ascii=False, indent=2)}\n=== END REQUEST ===")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    to = settings.get("llm_timeout", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT
    async with httpx.AsyncClient(timeout=httpx.Timeout(float(to), connect=CONNECT_TIMEOUT)) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if debug:
            _debug_print(f"\n=== LLM RESPONSE ===\nStatus: {resp.status_code}\nBody:\n{json.dumps(data, ensure_ascii=False, indent=2)}\n=== END RESPONSE ===")
        usage = data.get("usage", {})
        if usage:
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)
            cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
            cache_hit_rate = f"{(cached_tokens / prompt_tokens * 100):.1f}%" if prompt_tokens > 0 else "N/A"
            print(f"[TOKEN] input={prompt_tokens} output={completion_tokens} total={total_tokens} cache_hit={cache_hit_rate}")
        return data["choices"][0]["message"]

# ---- LLM CLIENT (streaming) ----
async def call_llm_stream(messages, settings):
    """Stream LLM response chunks. Yields text deltas."""
    url = (settings.get("llm_base_url", "") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    key = settings.get("llm_api_key", "")
    model = settings.get("llm_model", "") or "gpt-4o"
    payload = {
        "model": model, "messages": messages, "temperature": LLM_TEMPERATURE, "max_tokens": LLM_MAX_TOKENS,
        "stream": True, "stream_options": {"include_usage": True}
    }
    extra_body_str = settings.get("llm_extra_body", "")
    if extra_body_str and extra_body_str.strip():
        try:
            extra_body = json.loads(extra_body_str)
            payload["extra_body"] = extra_body
        except json.JSONDecodeError:
            pass
    debug = settings.get("llm_debug", False)
    if debug:
        _debug_print(f"\n=== LLM STREAM REQUEST ===\nURL: {url}\nModel: {model}\nPayload:\n{json.dumps(_sanitize_payload_for_debug(payload), ensure_ascii=False, indent=2)}\n=== END STREAM REQUEST ===")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    to = settings.get("llm_timeout", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT
    async with httpx.AsyncClient(timeout=httpx.Timeout(float(to), connect=CONNECT_TIMEOUT)) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            if debug:
                _debug_print(f"=== LLM STREAM RESPONSE started (status: {resp.status_code}) ===")
            streamed_text = ""
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            streamed_text += content
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        pass
            if debug:
                _debug_print(f"=== LLM STREAM RESPONSE ===\n{streamed_text}\n=== END STREAM RESPONSE ===")

# ---- COMPREHENSION (one-time deep summary) ----
async def generate_comprehension(book_id, save_id):
    """Generate a structured summary of Setting + Index using high-reasoning LLM."""
    settings = load_settings()
    if not settings.get("llm_api_key") or settings["llm_api_key"] == "sk-placeholder":
        raise RuntimeError("请先在设置中配置 LLM API Key")

    setting = load_md(BOOKS_DIR / book_id / "setting.md")
    index = load_md(BOOKS_DIR / book_id / "index.md")
    cfg = load_json(BOOKS_DIR / book_id / "config.json")

    system = f"""You are a story analyst for the narrative engine of "{cfg['title']}".
Read the Setting and Story Index below carefully. Produce a concise structured summary in Chinese covering:
1. Key characters and their relationships, personalities, motivations
2. World rules, power systems, important locations
3. Major plot arcs and turning points per chapter/section
4. The protagonist's current situation at the story's starting point

IMPORTANT: After the summary, append a "Section Map" section listing each chapter with its section IDs in a JSON array format, like:
## Section Map
- ch1: ["ch1_1", "ch1_2", "ch1_3"]
- ch2: ["ch2_1", "ch2_2"]
This map is critical for the narrative engine to load relevant source sections on demand.

Keep the summary under 2000 words. Write in plain paragraphs, no JSON needed (except the Section Map at the end)."""

    user = f"## Setting\n{setting}\n\n## Story Index\n{index}"

    comp_settings = dict(settings)
    comp_settings["llm_extra_body"] = json.dumps({"reasoning_effort": "high"})

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    resp = await call_llm(messages, comp_settings)
    summary = resp.get("content", "").strip()
    if not summary:
        raise RuntimeError("LLM 未能生成理解摘要")

    if len(summary) > COMPREHENSION_MAX_CHARS:
        summary = summary[:COMPREHENSION_MAX_CHARS] + "\n\n...(truncated)"

    save_md(SAVES_DIR / save_id / "comprehension.md", summary)
    return summary

def load_comprehension(save_id):
    """Load cached comprehension summary."""
    return load_md(SAVES_DIR / save_id / "comprehension.md")

# ---- SYSTEM PROMPT BUILDERS ----
def build_system_prompt(book_id, save_id=None):
    """System prompt optimized for streaming: newline-separated paragraphs."""
    cfg = load_json(BOOKS_DIR / book_id / "config.json")
    parts = ["You are StoryDive's narrative engine for " + cfg["title"] + "."]

    settings = load_settings()
    use_comprehension = settings.get("comprehension", True)

    if save_id and use_comprehension:
        comp = load_comprehension(save_id)
        if comp.strip():
            parts.append(f"\n## Story Comprehension\n{comp}")
        else:
            setting = load_md(BOOKS_DIR / book_id / "setting.md")
            if setting.strip():
                parts.append(f"\n## Setting\n{setting}")
            index = load_md(BOOKS_DIR / book_id / "index.md")
            if index.strip():
                parts.append(f"\n## Story Index\n{index}")
    else:
        setting = load_md(BOOKS_DIR / book_id / "setting.md")
        if setting.strip():
            parts.append(f"\n## Setting\n{setting}")
        index = load_md(BOOKS_DIR / book_id / "index.md")
        if index.strip():
            parts.append(f"\n## Story Index\n{index}")

    if save_id:
        memo = load_md(SAVES_DIR / save_id / "memo.md")
        if memo.strip():
            parts.append(f"\n## Current Memo\n{memo[:MEMO_MAX_CHARS]}")
        scfg = load_save_config(save_id)
        ref_sections = scfg.get("reference_sections", [])
        if ref_sections:
            parts.append("\n## Reference Source Sections\n")
            total_ref_chars = 0
            max_ref_chars = REFERENCE_MAX_CHARS
            for sec_id in ref_sections:
                content = load_source_section(book_id, sec_id)
                if content:
                    remaining = max_ref_chars - total_ref_chars
                    if remaining <= 0:
                        break
                    if len(content) > remaining:
                        content = content[:remaining] + "\n...(truncated)"
                    parts.append(f"\n### {sec_id}\n{content}")
                    total_ref_chars += len(content)

    parts.append("""
## Core Rules
1. Write narrative paragraphs separated by blank lines.
2. Narration paragraphs: plain text describing actions, scenery, internal thoughts.
3. Dialogue paragraphs: start with "Speaker: " then the dialogue. Example: "Emilia: Where am I?"
   For dialogue, you may hint expression in parentheses after the speaker name, e.g. "Speaker (expression): text".
   Common expressions: neutral, happy, sad, angry, surprised, determined, nervous, scared, calm, confused, shocked, weary, laughing, embarrassed, smug, worried, grinning, suspicious.
4. Use third-person limited POV following the protagonist. Show their thoughts and perceptions naturally within narration.
5. Generate 4-8 paragraphs. Last paragraph must be a natural break point for player input.
6. Maintain the original work's language style, pacing, and tone. Match the source material's prose quality.
7. DO NOT output JSON or code blocks. Output plain text paragraphs only, separated by blank lines.

## Narrative Quality
- Write vivid, immersive prose. Show, don't tell.
- Blend dialogue with action and description. Avoid long stretches of pure dialogue.
- Each paragraph should advance the story meaningfully.
- Respect the established world rules, power systems, and character personalities.
- Pay close attention to the timeline: the source material may use flashbacks or non-linear narrative techniques. Follow the story's chronological order, starting from the earliest events. Use the comprehension and index to determine the correct temporal sequence.
- When the player takes an action that deviates from the original plot, consult the comprehension to judge whether the deviation may intersect with characters, locations, or events not covered by currently loaded reference sections. If so, call `set_reference_sections` (see below).

## Tools Available
You have access to the following tools. Call them when appropriate, using the tool calling mechanism. After calling a tool, wait for the result, then generate the narrative.

- `update_memo(memo_text)`: Update the memo with important story state, character relationships, evolving plot clues, and any new information worth remembering. The memo persists across requests and helps maintain consistency. Write concisely in Chinese.
- `set_reference_sections(section_ids)`: Set which source sections to load as reference. Pass an array of section IDs like ["ch1_1", "ch1_2"] or [] to clear. Use the Section Map in the comprehension to find relevant section IDs. Call this when the story moves to a new scene/chapter or when the player's actions intersect with unloaded content.

## Strategy
- Default: skip tools and generate narrative paragraphs immediately.
- Call tools when:
  - The story has clearly moved into a new scene or chapter needing different reference sections → call `set_reference_sections`.
  - You have learned critical new plot/character information worth recording → call `update_memo`.
  - The player's action deviates from the original plot: check if the deviation may intersect with characters, locations, or events not covered by currently loaded reference sections. If so, call `set_reference_sections` to load the relevant source material.
- Keep memo updates concise and incremental. Focus on what changed or what's newly discovered.
""")

    parts.append("\n## CRITICAL FORMAT REMINDER\n- EVERY dialogue line MUST start with \"SpeakerName: \" (e.g. \"Emilia: Where am I?\")\n- Narration is plain text without any prefix.\n- Separate each paragraph with ONE blank line.\n- NEVER output JSON, code blocks, or markdown formatting.")
    return "\n".join(parts)

# ---- NARRATIVE GENERATION (non-streaming, with tool calling) ----
async def generate_narrative(book_id, save_id, action=None, speak=False, regret=False, accelerate=False):
    settings = load_settings()
    if not settings.get("llm_api_key") or settings["llm_api_key"] == "sk-placeholder":
        raise RuntimeError("请先在设置中配置 LLM API Key")

    cfg = load_json(BOOKS_DIR / book_id / "config.json")
    story = load_md(SAVES_DIR / save_id / "story.md")
    protagonist = cfg.get("protagonist", "protagonist")

    sp = build_system_prompt(book_id, save_id)
    parts = [f'# Script: {cfg["title"]}', f'# Protagonist: {protagonist}']
    if speak and action:
        parts.append(f'\n## Player Action (Speak)\n[{protagonist}] said: "{action}"\nGenerate story based on this dialogue.')
    elif action:
        parts.append(f'\n## Player Action\n{action}\nGenerate story based on this.')
    else:
        parts.append('\n## Begin\nStart the story from the beginning.')
    if regret:
        parts.append('\n## Regret\nRetract/undo the last narrative segment. Rewind the story state.')
    if accelerate:
        parts.append('\n## Accelerate\nFast-forward through time. Summarize transition under 200 words, jump to next key scene.')

    story_snip = story[-1*STORY_TAIL_CHARS:] if len(story) > STORY_TAIL_CHARS else story
    parts.append(f'\n## Current Story (tail)\n{story_snip}')
    messages = [
        {"role": "system", "content": sp},
        {"role": "user", "content": "\n".join(parts)}
    ]

    max_tool_rounds = MAX_TOOL_ROUNDS
    for round_num in range(max_tool_rounds):
        resp_msg = await call_llm(messages, settings, tools=TOOL_DEFS)
        tool_calls = resp_msg.get("tool_calls")
        if tool_calls:
            messages.append({"role": "assistant", "content": resp_msg.get("content"), "tool_calls": tool_calls})
            for tc in tool_calls:
                tool_result = execute_tool_call(tc, book_id, save_id)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})
            messages[0]["content"] = build_system_prompt(book_id, save_id)
            continue

        content_text = resp_msg.get("content", "")
        paragraphs = [p.strip() for p in content_text.split("\n\n") if p.strip()]
        result = []
        for p in paragraphs:
            p_clean = re.sub(r'^\d+[\.\),、]\s*', '', p)
            p_clean = re.sub(r'^[-\*]\s*', '', p_clean)
            para = _parse_paragraph_line(p_clean)
            if para:
                result.append(para)
        if len(result) >= 2:
            return result
        if round_num < max_tool_rounds - 1:
            messages.append({"role": "assistant", "content": content_text})
            messages.append({"role": "user", "content": 'You must output narrative paragraphs separated by blank lines. Each dialogue line must start with "SpeakerName: ". Narration lines are plain text. No JSON, no code blocks.'})
            continue
        raise RuntimeError("LLM 连续多次未返回有效段落，请重试")

    raise RuntimeError("LLM 未返回有效段落")

# ---- NARRATIVE GENERATION (streaming) ----
async def generate_narrative_stream(book_id, save_id, action=None, speak=False, regret=False, accelerate=False):
    """Generator that yields SSE event strings for streaming narrative generation."""
    settings = load_settings()
    if not settings.get("llm_api_key") or settings["llm_api_key"] == "sk-placeholder":
        yield f"data: {json.dumps({'error': '请先在设置中配置 LLM API Key'})}\n\n"
        return

    cfg = load_json(BOOKS_DIR / book_id / "config.json")
    story = load_md(SAVES_DIR / save_id / "story.md")
    protagonist = cfg.get("protagonist", "protagonist")

    sp = build_system_prompt(book_id, save_id)
    parts = [f'# Script: {cfg["title"]}', f'# Protagonist: {protagonist}']
    if speak and action:
        parts.append(f'\n## Player Action (Speak)\n[{protagonist}] said: "{action}"')
    elif action:
        parts.append(f'\n## Player Action\n{action}')
    else:
        parts.append('\n## Begin\nStart the story from the beginning.')
    if regret:
        parts.append('\n## Regret\nRetract/undo the last narrative segment.')
    if accelerate:
        parts.append('\n## Accelerate\nFast-forward through time.')

    story_snip = story[-1*STORY_TAIL_CHARS:] if len(story) > STORY_TAIL_CHARS else story
    parts.append(f'\n## Current Story (tail)\n{story_snip}')

    # Add format instruction as a hard constraint in the user prompt
    parts.append('\n## OUTPUT FORMAT (MANDATORY)\n- Dialogue: "Speaker: text" (e.g. "Emilia: I understand.")\n- Narration: plain text without prefix\n- Separate paragraphs with ONE blank line\n- NO JSON, NO markdown, NO code blocks')

    messages = [
        {"role": "system", "content": sp},
        {"role": "user", "content": "\n".join(parts)}
    ]

    try:
        buffer = ""
        paragraphs_emitted = 0
        async for delta in call_llm_stream(messages, settings):
            buffer += delta
            yield f"data: {json.dumps({'type': 'partial', 'text': delta})}\n\n"

            while "\n\n" in buffer:
                idx = buffer.index("\n\n")
                para_text = buffer[:idx].strip()
                buffer = buffer[idx + 2:]
                if para_text:
                    para = _parse_paragraph_line(para_text)
                    if para:
                        paragraphs_emitted += 1
                        yield f"data: {json.dumps({'type': 'paragraph', 'index': paragraphs_emitted, 'para': para})}\n\n"

        remaining = buffer.strip()
        if remaining:
            para = _parse_paragraph_line(remaining)
            if para:
                paragraphs_emitted += 1
                yield f"data: {json.dumps({'type': 'paragraph', 'index': paragraphs_emitted, 'para': para})}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'total': paragraphs_emitted})}\n\n"

    except Exception as e:
        import traceback, logging
        traceback.print_exc()
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

def _parse_paragraph_line(text):
    """Parse a single paragraph line into {type, text, speaker?}."""
    text = text.strip()
    if not text:
        return None
    m = re.match(r'^(.+?):\s+(.+)$', text)
    if m:
        speaker = m.group(1).strip()
        if speaker and len(speaker) < SPEAKER_MAX_LEN and not speaker.startswith("http") and not speaker.startswith("#"):
            return {"type": "dialogue", "speaker": speaker, "text": m.group(2).strip()}
    return {"type": "narration", "text": text}

