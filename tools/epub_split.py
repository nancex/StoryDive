#!/usr/bin/env python3
"""epub_split.py — 遍历 books 文件夹中的 .epub/.mobi 文件，按章节提取为 ch1.txt, ch2.txt..."""

import re
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 依赖检查
# ---------------------------------------------------------------------------
try:
    import ebooklib
    from ebooklib import epub
    EPUB_OK = True
except ImportError:
    EPUB_OK = False

try:
    from mobi.extract import extract as mobi_extract
    MOBI_OK = True
except ImportError:
    MOBI_OK = False

try:
    from bs4 import BeautifulSoup
    BS_OK = True
except ImportError:
    BS_OK = False


# ===================================================================
# 工具函数
# ===================================================================

def find_book_dirs(books_root: Path) -> list[dict]:
    """在 books/ 下找出所有包含 .epub 或 .mobi 的子文件夹。"""
    results = []
    if not books_root.exists():
        print(f"[错误] 目录不存在: {books_root}")
        return results
    for sub in sorted(books_root.iterdir()):
        if not sub.is_dir():
            continue
        ebook_files = sorted(
            [f for f in sub.iterdir() if f.suffix.lower() in (".epub", ".mobi")]
        )
        if ebook_files:
            results.append({"dir": sub, "files": ebook_files})
    return results


def html_to_text(html_fragment: str) -> str:
    """将 HTML 片段转为保留换行的纯文本。"""
    soup = BeautifulSoup(html_fragment, "html.parser")
    # <br> → \n
    for br in soup.find_all("br"):
        br.replace_with("\n")
    # <p> 前后加换行（get_text 已处理大部分，但保险）
    text = soup.get_text(separator="\n")
    # 清理：合并连续空行，trim 每行
    lines = []
    prev_empty = False
    for ln in text.splitlines():
        stripped = ln.strip()
        if not stripped:
            if not prev_empty:
                lines.append("")
            prev_empty = True
        else:
            lines.append(stripped)
            prev_empty = False
    return "\n".join(lines).strip()


def extract_epub_chapters(epub_path: Path, out_dir: Path) -> int:
    """从 EPUB 提取章节文本，写入 ch1.txt …"""
    book = epub.read_epub(str(epub_path))
    chapter_idx = 0
    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        content = item.get_content().decode("utf-8", errors="replace")
        text = html_to_text(content)
        if len(text) < 200:
            continue
        chapter_idx += 1
        out_path = out_dir / f"ch{chapter_idx}.txt"
        out_path.write_text(text, encoding="utf-8")
        print(f"    -> {out_path.name}  ({len(text)} 字符)")
    return chapter_idx


def extract_mobi_chapters(mobi_path: Path, out_dir: Path) -> int:
    """从 MOBI 提取章节文本：解压 → 按 <mbp:pagebreak> 拆分 → 每段写为 chX.txt。"""
    if not BS_OK:
        print("    [错误] 缺少 beautifulsoup4，请运行: pip install beautifulsoup4")
        return 0

    print("    正在解压 MOBI ...")
    extract_dir_str, book_html_str = mobi_extract(str(mobi_path))
    extract_dir = Path(extract_dir_str)
    book_html = Path(book_html_str)
    print(f"    解压到: {extract_dir}")

    try:
        html_content = book_html.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html_content, "html.parser")
        body = soup.find("body") or soup

        # 用特殊标记替换 <mbp:pagebreak>，然后整体转文本再按标记切分
        PAGE_MARKER = "___PAGE_BREAK___"
        for pb in body.find_all("mbp:pagebreak"):
            pb.replace_with(f"\n{PAGE_MARKER}\n")

        full_text = html_to_text(str(body))

        # 按标记切分
        sections = full_text.split(PAGE_MARKER)

        chapter_idx = 0
        skipped = 0
        for sec in sections:
            text = sec.strip()
            if len(text) < 300:
                skipped += 1
                continue
            chapter_idx += 1
            out_path = out_dir / f"ch{chapter_idx}.txt"
            out_path.write_text(text, encoding="utf-8")
            print(f"    -> {out_path.name}  ({len(text)} 字符)")

        print(f"    共 {chapter_idx} 个章节（跳过 {skipped} 个过短段落）")
        return chapter_idx

    except Exception as e:
        print(f"    [错误] HTML 解析失败: {e}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        if extract_dir.exists():
            shutil.rmtree(extract_dir, ignore_errors=True)


# ===================================================================
# 主流程
# ===================================================================

def main():
    books_root = Path(__file__).resolve().parent.parent / "books"

    candidates = find_book_dirs(books_root)
    if not candidates:
        print("没有找到包含 .epub 或 .mobi 文件的子文件夹。")
        return

    print("\n可用的电子书：")
    print("-" * 50)
    for idx, entry in enumerate(candidates, 1):
        names = ", ".join(f.name for f in entry["files"])
        print(f"  [{idx}] {entry['dir'].name}/  ({names})")
    print("-" * 50)

    while True:
        try:
            choice = input("请输入序号（q 退出）: ").strip()
            if choice.lower() == "q":
                print("已退出。")
                return
            idx = int(choice) - 1
            if 0 <= idx < len(candidates):
                selected = candidates[idx]
                break
            print(f"无效序号，请输入 1-{len(candidates)}")
        except (ValueError, EOFError):
            print("无效输入，请输入数字。")

    book_dir = selected["dir"]
    print(f"\n正在处理: {book_dir.name}/")
    total_chapters = 0

    for f in selected["files"]:
        suffix = f.suffix.lower()
        print(f"  读取: {f.name}  ({suffix})")

        if suffix == ".epub":
            if not EPUB_OK:
                print("    [错误] 缺少 epub 支持库，请运行: pip install ebooklib beautifulsoup4")
                continue
            n = extract_epub_chapters(f, book_dir)
            total_chapters += n

        elif suffix == ".mobi":
            if not MOBI_OK:
                print("    [错误] 缺少 mobi 支持库，请运行: pip install mobi beautifulsoup4")
                continue
            try:
                n = extract_mobi_chapters(f, book_dir)
                total_chapters += n
            except Exception as e:
                print(f"    [错误] MOBI 转换失败: {e}")

    print(f"\n完成！共提取 {total_chapters} 个章节到 {book_dir}/ 下。")


if __name__ == "__main__":
    main()
