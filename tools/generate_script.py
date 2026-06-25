#!/usr/bin/env python3
"""generate_script.py — LLM-based summary + index.md & setting.md generation.

Three modes:
  1. Fast: parallel LLM summaries -> programmatic index.md assembly
  2. Batch: single LLM call with all content (3 sub-actions)
  3. Pipeline: sequential index & setting passing (existing behavior)
"""

import json
import logging
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
try:
    from openai import OpenAI
    OPENAI_OK = True
except ImportError:
    OPENAI_OK = False
    print("[ERROR] Missing openai. Run: pip install openai")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("generate_script")

# ===================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BOOKS_ROOT = PROJECT_ROOT / "books"
SETTINGS_PATH = PROJECT_ROOT / "settings.json"
# ===================================================================
# Tunable LLM parameters (max_tokens / temperature)
# ===================================================================
SUMMARY_MAX_TOKENS = 1024
SUMMARY_TEMPERATURE = 0.5

BATCH_MAX_TOKENS = 8192*2
BATCH_INDEX_TEMP = 0.6
BATCH_SETTING_TEMP = 0.6

PIPELINE_INDEX_MAX_TOKENS = 4096
PIPELINE_INDEX_TEMP = 0.3

PIPELINE_SETTING_MAX_TOKENS = 4096
PIPELINE_SETTING_TEMP = 0.5

FIX_FORMAT_MAX_TOKENS = 4096
FIX_FORMAT_TEMP = 0.1



def load_settings() -> dict:
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_llm_client(settings: dict) -> OpenAI:
    return OpenAI(
        api_key=settings["llm_api_key"],
        base_url=settings["llm_base_url"],
        timeout=300,
    )


def find_source_dirs(books_root: Path) -> list[Path]:
    results = []
    if not books_root.exists():
        return results
    for sub in sorted(books_root.iterdir()):
        if not sub.is_dir():
            continue
        src = sub / "source"
        if src.is_dir() and list(src.glob("ch*_*.txt")):
            results.append(sub)
    return results


def subsection_sort_key(path: Path) -> tuple:
    m = re.search(r"ch(\d+)_(\d+)\.txt$", path.name)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (0, 0)


def call_llm(client, model, system_prompt, user_prompt,
             max_tokens=4096, temperature=0.6) -> str:
    log.info(f"  -> LLM call (max_tokens={max_tokens})...")
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        content = resp.choices[0].message.content
        log.info(f"  <- LLM returned {len(content)} chars")
        return content
    except Exception as e:
        log.error(f"  LLM call failed: {e}")
        raise


# ===================================================================
# Prompts
# ===================================================================

SUMMARY_SYSTEM = """You are a professional literary editor. Write a detailed summary
for the given subsection (at least 150 words), covering key plot developments,
character interactions, scene descriptions, and emotional tone.

Output only the summary text, no prefixes or markers."""


INDEX_REFINE_SYSTEM = """You are an editor responsible for a novel's index.md file.
You will receive the current index.md and ALL subsection contents with their summaries.

Please review and refine the index.md. Ensure all entries are accurate and summaries are detailed.

CRITICAL — You MUST follow this EXACT format:

# Book Title
## 第一章：Chapter Title
- ch1_1: detailed summary text (at least 100 chars, covering plot, characters, scene)
- ch1_2: detailed summary text
## 第二章：Chapter Title
- ch2_1: detailed summary text

Rules:
1. Chapter headings MUST use Chinese: 第一章, 第二章, 第三章, etc. (NOT "Chapter 1")
2. Each subsection line: "- chX_Y: summary" (no extra indentation or formatting)
3. Do NOT add markdown headings (###, ####) inside summaries
4. Output ONLY the complete index.md, no extra prefixes or explanations"""


INDEX_AND_SETTING_SYSTEM = """You are a literary analyst and editor.
You will receive the current index.md, setting.md, and ALL subsection contents.

Your tasks:
1. Refine and improve the index.md (fix vague summaries, ensure accuracy)
2. Create or update the setting.md with worldbuilding, characters, and writing style

CRITICAL — index.md MUST use this EXACT format:
# Book Title
## 第一章：Chapter Title
- ch1_1: detailed summary (at least 100 chars)
- ch1_2: detailed summary
## 第二章：Chapter Title
- ch2_1: detailed summary

Rules for index.md:
- Chapter headings MUST use Chinese: 第一章, 第二章, etc. (NOT "Chapter 1")
- Each subsection line: "- chX_Y: summary"
- Do NOT add extra markdown headings inside summaries

Output your response in TWO clearly marked sections:

===INDEX===
(complete refined index.md)

===SETTING===
(complete setting.md with ## 世界观设定, ## 主要角色, ## 写作规范)"""


SETTING_ONLY_SYSTEM = """You are a literary analyst.
You will receive the current setting.md and ALL subsection contents.

Create or update the setting.md with:
- ## World Setting: era, location, society, any fantasy/sci-fi elements
- ## Main Characters: appearance, personality, relationships for each important character
- ## Writing Style: narrative perspective, tone, dialogue style, special techniques

Output the complete setting.md, no extra prefixes."""


FIX_FORMAT_SYSTEM = """You are a meticulous editor. Your ONLY job is to fix the FORMAT of an index.md file.
Do NOT change, add, or remove any content — ONLY fix the formatting.

Required EXACT format:
# Book Title
## 第一章：Chapter Title
- ch1_1: summary text
- ch1_2: summary text
## 第二章：Chapter Title
- ch2_1: summary text

Rules:
1. Chapter headings MUST use Chinese numerals: 第一章, 第二章, 第三章, etc.
2. If a chapter has a title, format as: ## 第X章：Title
3. If no title is present, use: ## 第X章
4. Subsection lines MUST be: "- chX_Y: summary text"
5. Remove any extra markdown headings (###, ####) inside summaries
6. Keep ALL summary text exactly as-is — only fix formatting
7. Output only the fixed index.md, no extra text"""


INDEX_SYSTEM_PIPELINE = """You are an editor maintaining an index.md file.
You will receive the current index.md and a new subsection summary to add.

Add it at the correct position. CRITICAL — You MUST use this EXACT format:

# Book Title
## 第一章：Chapter Title
- ch1_1: summary
- ch1_2: summary
## 第二章：Chapter Title
- ch2_1: summary

Rules:
1. Chapter headings MUST use Chinese: 第一章, 第二章, 第三章, etc. (NOT "Chapter 1")
2. If starting a new chapter: "## 第X章：" (infer title from summary if possible)
3. Keep all existing content; only append at the end
4. Output the complete updated index.md, no extra prefixes"""


SETTING_SYSTEM_PIPELINE = """You are a literary analyst maintaining a setting.md.
You will receive the current setting.md and new subsection content.

Update the document (## World Setting, ## Main Characters, ## Writing Style):
1. Add new worldbuilding info
2. Add/update character entries (appearance, personality, relationships)
3. Add new writing style observations
4. Do NOT delete correct existing info
5. Output complete setting.md, no extra prefixes"""


# ===================================================================
# Mode 1: Fast Parallel Summary + Programmatic Index
# ===================================================================

class SummaryWorker(threading.Thread):
    """Only does LLM summary. Used by Mode 1."""

    def __init__(self, worker_id, subsection_path, label, settings, title, status_dict, result_list):
        super().__init__(name=f"Worker-{worker_id}", daemon=False)
        self.worker_id = worker_id
        self.subsection_path = subsection_path
        self.label = label
        self.settings = settings
        self.title = title
        self.status_dict = status_dict
        self.result_list = result_list
        self.summary = ""

    def run(self):
        try:
            self.status_dict[self.worker_id] = "summarizing"
            client = get_llm_client(self.settings)
            model = self.settings["llm_model"]

            raw_text = self.subsection_path.read_text(encoding="utf-8")
            if len(raw_text) > 6000:
                raw_text = raw_text[:6000]

            user_prompt = f"Book: {self.title}\nSubsection: {self.label}\n\nContent:\n{raw_text}"

            self.summary = call_llm(
                client, model, SUMMARY_SYSTEM, user_prompt,
                max_tokens=SUMMARY_MAX_TOKENS, temperature=SUMMARY_TEMPERATURE,
            )
            self.status_dict[self.worker_id] = "done"
            self.result_list.append({
                "label": self.label,
                "summary": self.summary,
                "worker_id": self.worker_id,
            })
            log.info(f"[{self.label}] summary done ({len(self.summary)} chars)")
        except Exception as e:
            log.error(f"[{self.label}] error: {e}")
            self.status_dict[self.worker_id] = f"error: {e}"
            self.result_list.append({
                "label": self.label,
                "summary": f"(Error: {e})",
                "worker_id": self.worker_id,
            })


def print_mode1_status(status_dict, workers):
    for w in workers:
        wid = w.worker_id
        s = status_dict.get(wid, "pending")
        icon = {"pending": "[ ]", "summarizing": "[...]", "done": "[OK]"}.get(s, "[?]")
        print(f"  [{w.label}] {icon} {s}")


def mode1_parallel_summary(book_dir, settings, title, author, source_dir, subsection_files):
    total = len(subsection_files)
    print(f"\nMode 1: Parallel Summary ({total} subsections)")
    print("-" * 50)

    status_dict = {}
    result_list = []
    workers = []

    for i, sec_path in enumerate(subsection_files):
        m = re.search(r"ch(\d+)_(\d+)", sec_path.stem)
        if not m:
            continue
        label = f"ch{m.group(1)}_{m.group(2)}"
        w = SummaryWorker(
            worker_id=i + 1,
            subsection_path=sec_path,
            label=label,
            settings=settings,
            title=title,
            status_dict=status_dict,
            result_list=result_list,
        )
        workers.append(w)
        status_dict[i + 1] = "pending"

    log.info(f"Starting {len(workers)} summary workers...")
    for w in workers:
        w.start()

    # Poll status
    prev_snapshot = ""
    print("\n" + "=" * 50)
    print(f"Initial ({len(workers)} workers)")
    print_mode1_status(status_dict, workers)
    print("=" * 50)

    while True:
        time.sleep(2)
        all_done = all(
            status_dict.get(w.worker_id, "") in ("done",)
            or str(status_dict.get(w.worker_id, "")).startswith("error")
            for w in workers
        )
        current = str([status_dict.get(w.worker_id, "") for w in workers])
        if current != prev_snapshot or all_done:
            prev_snapshot = current
            done_count = sum(1 for w in workers if status_dict.get(w.worker_id, "") in ("done",) or str(status_dict.get(w.worker_id, "")).startswith("error"))
            print("\n" + "=" * 50)
            print(f"Progress: {done_count}/{len(workers)}")
            print_mode1_status(status_dict, workers)
            print("=" * 50)
        if all_done:
            break

    for w in workers:
        w.join(timeout=5)

    # Build index.md programmatically
    print("\nAssembling index.md ...")
    result_list.sort(key=lambda r: subsection_sort_key(Path(f"ch{r['label']}.txt")))

    lines = [f"# {title}"]
    prev_ch = 0
    for r in result_list:
        m = re.search(r"ch(\d+)_(\d+)", r["label"])
        if not m:
            continue
        ch = int(m.group(1))
        if ch != prev_ch:
            lines.append(f"## Chapter {ch}")
            prev_ch = ch
        lines.append(f"- {r['label']}: {r['summary']}")
        lines.append("")

    index_md = "\n".join(lines)
    index_path = book_dir / "index.md"
    index_path.write_text(index_md, encoding="utf-8")
    print(f"index.md written: {index_path} ({len(index_md)} chars)")
    print("Done (Mode 1).")


# ===================================================================
# Mode 2: Batch Single LLM Call
# ===================================================================


def fix_format_index(book_dir, settings, title):
    """Send existing index.md to LLM for format-only fixes."""
    index_path = book_dir / "index.md"
    if not index_path.exists():
        print("No index.md found to fix.")
        return False

    existing = index_path.read_text(encoding="utf-8")
    print(f"\nSending index.md for format fix ({len(existing)} chars)...")

    client = get_llm_client(settings)
    model = settings["llm_model"]

    user_prompt = f"Book: {title}\n\nCurrent index.md (fix formatting only, keep all content):\n{existing}"

    fixed = call_llm(
        client, model, FIX_FORMAT_SYSTEM, user_prompt,
        max_tokens=FIX_FORMAT_MAX_TOKENS, temperature=FIX_FORMAT_TEMP,
    )
    index_path.write_text(fixed, encoding="utf-8")
    print(f"Format fixed: {index_path} ({len(fixed)} chars)")
    return True


def mode2_batch_llm(book_dir, settings, title, author, source_dir, subsection_files):
    total = len(subsection_files)
    print(f"\nMode 2: Batch LLM ({total} subsections)")
    print("-" * 50)

    print("\nSub-actions:")
    print("  [1] Refine index.md only")
    print("  [2] Refine index.md AND generate/update setting.md")
    print("  [3] Generate/update setting.md only (no index change)")

    while True:
        sub = input("Choose sub-action (1/2/3): ").strip()
        if sub in ("1", "2", "3"):
            break
        print("Invalid, enter 1, 2, or 3.")

    # Build all content
    print("\nReading all subsections...")
    all_content_parts = []
    for sec_path in subsection_files:
        m = re.search(r"ch(\d+)_(\d+)", sec_path.stem)
        label = f"ch{m.group(1)}_{m.group(2)}" if m else sec_path.stem
        text = sec_path.read_text(encoding="utf-8")
        if len(text) > 3000:
            text = text[:3000] + "\n...(truncated)"
        all_content_parts.append(f"=== {label} ===\n{text}")
    all_content = "\n\n".join(all_content_parts)

    # Read existing index/setting if they exist
    index_path = book_dir / "index.md"
    setting_path = book_dir / "setting.md"
    existing_index = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    existing_setting = setting_path.read_text(encoding="utf-8") if setting_path.exists() else ""

    client = get_llm_client(settings)
    model = settings["llm_model"]

    if sub == "1":
        log.info("Mode 2.1: Refining index.md only...")
        user_prompt = (
            f"Book: {title}\nAuthor: {author}\n\n"
            f"Current index.md:\n{existing_index if existing_index else '(empty)'}\n\n"
            f"=== ALL SUBSECTIONS ===\n{all_content}"
        )
        response = call_llm(client, model, INDEX_REFINE_SYSTEM, user_prompt, max_tokens=BATCH_MAX_TOKENS, temperature=BATCH_INDEX_TEMP)
        index_path.write_text(response, encoding="utf-8")
        print(f"index.md written: {index_path}")

    elif sub == "2":
        log.info("Mode 2.2: Refining index.md + setting.md...")
        user_prompt = (
            f"Book: {title}\nAuthor: {author}\n\n"
            f"Current index.md:\n{existing_index if existing_index else '(empty)'}\n\n"
            f"Current setting.md:\n{existing_setting if existing_setting else '(empty)'}\n\n"
            f"=== ALL SUBSECTIONS ===\n{all_content}"
        )
        response = call_llm(client, model, INDEX_AND_SETTING_SYSTEM, user_prompt, max_tokens=BATCH_MAX_TOKENS, temperature=BATCH_INDEX_TEMP)

        # Parse two sections
        index_part = ""
        setting_part = ""
        if "===INDEX===" in response and "===SETTING===" in response:
            idx_start = response.find("===INDEX===") + len("===INDEX===")
            idx_end = response.find("===SETTING===")
            set_start = response.find("===SETTING===") + len("===SETTING===")
            index_part = response[idx_start:idx_end].strip()
            setting_part = response[set_start:].strip()
        else:
            # Fallback: try to split heuristically
            parts = response.split("===SETTING===")
            if len(parts) == 2:
                index_part = parts[0].replace("===INDEX===", "").strip()
                setting_part = parts[1].strip()
            else:
                log.warning("Could not parse INDEX/SETTING sections, writing raw response to both")
                index_part = response
                setting_part = response

        if index_part:
            index_path.write_text(index_part, encoding="utf-8")
            print(f"index.md written: {index_path}")
        if setting_part:
            setting_path.write_text(setting_part, encoding="utf-8")
            print(f"setting.md written: {setting_path}")

    elif sub == "3":
        log.info("Mode 2.3: Generating setting.md only...")
        user_prompt = (
            f"Book: {title}\nAuthor: {author}\n\n"
            f"Current setting.md:\n{existing_setting if existing_setting else '(empty, create from scratch)'}\n\n"
            f"=== ALL SUBSECTIONS ===\n{all_content}"
        )
        response = call_llm(client, model, SETTING_ONLY_SYSTEM, user_prompt, max_tokens=BATCH_MAX_TOKENS, temperature=BATCH_SETTING_TEMP)
        setting_path.write_text(response, encoding="utf-8")
        print(f"setting.md written: {setting_path}")

    # Offer format fix for index.md (if it was generated/modified)
    index_path = book_dir / "index.md"
    if index_path.exists() and sub in ("1", "2"):
        print("\n" + "-" * 40)
        fix_choice = input("Fix index.md formatting with a separate LLM call? (y/n): ").strip().lower()
        if fix_choice == "y":
            fix_format_index(book_dir, settings, title)

    print("Done (Mode 2).")


# ===================================================================
# Mode 3: Pipeline (existing behavior)
# ===================================================================

class PipelineWorker(threading.Thread):
    """Handles one subsection: summarize -> modify index -> modify setting."""

    def __init__(self, worker_id, subsection_path, label, chapter_num,
                 settings, title, author, prev_worker, is_first, status_dict):
        super().__init__(name=f"Worker-{worker_id}", daemon=False)
        self.worker_id = worker_id
        self.subsection_path = subsection_path
        self.label = label
        self.chapter_num = chapter_num
        self.settings = settings
        self.title = title
        self.author = author
        self.prev_worker = prev_worker
        self.is_first = is_first
        self.status_dict = status_dict

        self.summary = ""
        self.index_md = ""
        self.setting_md = ""
        self.client = None

        self.index_done = threading.Event()
        self.setting_done = threading.Event()

    def run(self):
        try:
            self.client = get_llm_client(self.settings)
            model = self.settings["llm_model"]
            self._phase_summarize(model)
            self._phase_modify_index(model)
            self._phase_modify_setting(model)
            self.status_dict[self.worker_id] = "done"
            log.info(f"[{self.label}] All phases complete")
        except Exception as e:
            log.error(f"[{self.label}] Fatal: {e}")
            self.status_dict[self.worker_id] = f"error: {e}"

    def _phase_summarize(self, model):
        self.status_dict[self.worker_id] = "summarizing"
        log.info(f"[{self.label}] Phase 1: summarizing...")
        raw_text = self.subsection_path.read_text(encoding="utf-8")
        if len(raw_text) > 6000:
            raw_text = raw_text[:6000]
        user_prompt = f"Book: {self.title}\nSubsection: {self.label}\n\nContent:\n{raw_text}"
        self.summary = call_llm(self.client, model, SUMMARY_SYSTEM, user_prompt,
                                max_tokens=SUMMARY_MAX_TOKENS, temperature=SUMMARY_TEMPERATURE)
        self.status_dict[self.worker_id] = "summary_done"
        log.info(f"[{self.label}] summary done ({len(self.summary)} chars)")

    def _phase_modify_index(self, model):
        self.status_dict[self.worker_id] = "waiting_index"
        log.info(f"[{self.label}] Phase 2: waiting for previous index...")
        if self.is_first:
            prev_index = ""
        else:
            self.prev_worker.index_done.wait()
            prev_index = self.prev_worker.index_md
            log.info(f"[{self.label}] received index ({len(prev_index)} chars)")

        self.status_dict[self.worker_id] = "modifying_index"
        is_new = (self.prev_worker is None or self.prev_worker.chapter_num != self.chapter_num)
        chapter_info = f"Chapter {self.chapter_num}" + (" (NEW)" if is_new else "")

        user_prompt = (
            f"Book: {self.title}\n"
            f"Current index.md:\n{prev_index if prev_index else '(empty)'}\n\n"
            f"---\nNew subsection:\n"
            f"- Label: {self.label}\n"
            f"- Belongs to: {chapter_info}\n"
            f"- Summary: {self.summary}\n"
        )
        self.index_md = call_llm(self.client, model, INDEX_SYSTEM_PIPELINE, user_prompt,
                                 max_tokens=PIPELINE_INDEX_MAX_TOKENS, temperature=PIPELINE_INDEX_TEMP)
        self.index_done.set()
        self.status_dict[self.worker_id] = "index_done"
        log.info(f"[{self.label}] index modified ({len(self.index_md)} chars)")

    def _phase_modify_setting(self, model):
        self.status_dict[self.worker_id] = "waiting_setting"
        log.info(f"[{self.label}] Phase 3: waiting for previous setting...")
        if self.is_first:
            prev_setting = ""
        else:
            self.prev_worker.setting_done.wait()
            prev_setting = self.prev_worker.setting_md
            log.info(f"[{self.label}] received setting ({len(prev_setting)} chars)")

        self.status_dict[self.worker_id] = "modifying_setting"
        raw_text = self.subsection_path.read_text(encoding="utf-8")
        if len(raw_text) > 4000:
            raw_text = raw_text[:4000]

        user_prompt = (
            f"Book: {self.title}\nAuthor: {self.author}\n"
            f"Current setting.md:\n{prev_setting if prev_setting else '(empty, create initial)'}\n\n"
            f"---\nNew content:\n{raw_text}"
        )
        self.setting_md = call_llm(self.client, model, SETTING_SYSTEM_PIPELINE, user_prompt,
                                   max_tokens=PIPELINE_SETTING_MAX_TOKENS, temperature=PIPELINE_SETTING_TEMP)
        self.setting_done.set()
        self.status_dict[self.worker_id] = "setting_done"
        log.info(f"[{self.label}] setting modified ({len(self.setting_md)} chars)")


PIPELINE_ICONS = {
    "pending":              "[ ]",
    "summarizing":          "[...]",
    "summary_done":         "[S]",
    "waiting_index":        "[wI]",
    "modifying_index":      "[mI]",
    "index_done":           "[I]",
    "waiting_setting":      "[wS]",
    "modifying_setting":    "[mS]",
    "setting_done":         "[S]",
    "done":                 "[OK]",
}


def print_pipeline_status(status_dict, workers):
    lines = []
    for w in workers:
        wid = w.worker_id
        raw = status_dict.get(wid, "pending")
        base = raw.split(":")[0]
        icon = PIPELINE_ICONS.get(base, "[?]")
        lines.append(f"  [{w.label}] {icon} {raw}")
    print("\n".join(lines))


def mode3_pipeline(book_dir, settings, title, author, source_dir, subsection_files):
    total = len(subsection_files)
    print(f"\nMode 3: Pipeline ({total} subsections)")
    print("-" * 50)

    status_dict = {}
    workers = []

    for i, sec_path in enumerate(subsection_files):
        m = re.search(r"ch(\d+)_(\d+)", sec_path.stem)
        if not m:
            continue
        ch_num = int(m.group(1))
        label = f"ch{m.group(1)}_{m.group(2)}"
        prev = workers[-1] if workers else None
        is_first = (i == 0)

        w = PipelineWorker(
            worker_id=i + 1,
            subsection_path=sec_path,
            label=label,
            chapter_num=ch_num,
            settings=settings,
            title=title,
            author=author,
            prev_worker=prev,
            is_first=is_first,
            status_dict=status_dict,
        )
        workers.append(w)
        status_dict[i + 1] = "pending"

    log.info(f"Starting {len(workers)} pipeline workers...")
    for w in workers:
        w.start()

    prev_snapshot = ""
    print("\n" + "=" * 50)
    print(f"Initial ({len(workers)} workers)")
    print_pipeline_status(status_dict, workers)
    print("=" * 50)

    while True:
        time.sleep(2)
        all_done = all(
            status_dict.get(w.worker_id, "") in ("done",)
            or str(status_dict.get(w.worker_id, "")).startswith("error")
            for w in workers
        )
        current = str([status_dict.get(w.worker_id, "") for w in workers])
        if current != prev_snapshot or all_done:
            prev_snapshot = current
            done_count = sum(1 for w in workers if status_dict.get(w.worker_id, "") in ("done",) or str(status_dict.get(w.worker_id, "")).startswith("error"))
            print("\n" + "=" * 50)
            print(f"Progress: {done_count}/{len(workers)}")
            print_pipeline_status(status_dict, workers)
            print("=" * 50)
        if all_done:
            break

    for w in workers:
        w.join(timeout=5)

    last = workers[-1]
    if last.index_md:
        ip = book_dir / "index.md"
        ip.write_text(last.index_md, encoding="utf-8")
        log.info(f"index.md -> {ip}")
    if last.setting_md:
        sp = book_dir / "setting.md"
        sp.write_text(last.setting_md, encoding="utf-8")
        log.info(f"setting.md -> {sp}")

    print("Done (Mode 3).")


# ===================================================================
# Main
# ===================================================================

def main():
    print("=" * 60)
    print("  StoryDive - Script Generator")
    print("=" * 60)

    if not OPENAI_OK:
        print("[ERROR] Missing openai. Run: pip install openai")
        return

    settings = load_settings()
    log.info(f"LLM: {settings['llm_base_url']} | model={settings['llm_model']}")

    book_dirs = find_source_dirs(BOOKS_ROOT)
    if not book_dirs:
        print("\nNo source/chX_Y.txt files found.")
        print("Run split_chapter.py first.")
        return

    print("\nAvailable books:")
    print("-" * 50)
    for idx, d in enumerate(book_dirs, 1):
        src = d / "source"
        count = len(list(src.glob("ch*_*.txt")))
        print(f"  [{idx}] {d.name}/  ({count} subsections)")
    print("-" * 50)

    while True:
        try:
            choice = input("Choose book (q to quit): ").strip()
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

    config_path = book_dir / "config.json"
    if config_path.exists():
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        title = cfg.get("title", book_dir.name)
        author = cfg.get("original_author", "Unknown")
    else:
        title = book_dir.name
        author = "Unknown"

    print(f"  Title: {title}")
    print(f"  Author: {author}")

    source_dir = book_dir / "source"
    subsection_files = sorted(source_dir.glob("ch*_*.txt"), key=subsection_sort_key)
    total = len(subsection_files)
    print(f"  Subsections: {total}")

    # === Mode Selection ===
    print("\n" + "=" * 50)
    print("Select Mode:")
    print("  [1] Fast     — parallel LLM summaries + programmatic index.md")
    print("  [2] Batch    — single LLM call with all content (3 sub-actions)")
    print("  [3] Pipeline — sequential index & setting passing (each sub gets LLM)")
    print("=" * 50)

    while True:
        mode = input("Choose mode (1/2/3): ").strip()
        if mode in ("1", "2", "3"):
            break
        print("Invalid, enter 1, 2, or 3.")

    if mode == "1":
        mode1_parallel_summary(book_dir, settings, title, author, source_dir, subsection_files)
    elif mode == "2":
        mode2_batch_llm(book_dir, settings, title, author, source_dir, subsection_files)
    elif mode == "3":
        mode3_pipeline(book_dir, settings, title, author, source_dir, subsection_files)


if __name__ == "__main__":
    main()
