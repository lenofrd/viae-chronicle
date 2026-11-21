"""文档与仓库结构一致性检查（架构门禁 P8-11）。

检查内容：
1. ``README.md`` 与 ``docs/**/*.md`` 中引用的仓库相对路径真实存在
   （防止文档把已删除/未实现的脚本描述为可用功能）；
2. README「仓库结构」代码块里的目录/文件条目与磁盘一致；
3. 正式运行入口脚本确实存在。

本地工作区目录（``data/``、``.ai/``、``.check/``、``.trae/``）不入库，
跳过其存在性检查。

用法（仓库根）：``python scripts/check_docs_config.py``；失败退出码 1。
"""
from __future__ import annotations

import os
import re

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

PATH_ROOTS = ("src", "config", "scripts", "tests", "viz", "docs")
IGNORED_ROOTS = {"data", ".ai", ".check", ".trae"}
PATH_RE = re.compile(
    r"(?<![\w./-])((?:%s)/[\w./-]*\.[A-Za-z0-9]+)" % "|".join(PATH_ROOTS)
)
TREE_HEADING = "## 仓库结构"
TREE_ENTRY_RE = re.compile(r"^(\s*)([A-Za-z0-9_.][\w./-]*)(?=\s{2,}\S|\s*$)")
ENTRY_POINTS = ("scripts/run_xigu.py", "src/vale/cli.py", "viz/sim_worker.py")


def _markdown_files() -> list[str]:
    files = [os.path.join(_ROOT, "README.md")]
    docs_root = os.path.join(_ROOT, "docs")
    for dirpath, _, filenames in os.walk(docs_root):
        for filename in sorted(filenames):
            if filename.endswith(".md"):
                files.append(os.path.join(dirpath, filename))
    return files


def _iter_text_paths(text: str):
    for match in PATH_RE.finditer(text):
        raw = match.group(1).rstrip(".,;:）)")
        if any(char in raw for char in "*{}<>$"):
            continue
        yield raw


def check_referenced_paths() -> list[str]:
    problems: list[str] = []
    for path in _markdown_files():
        rel_doc = os.path.relpath(path, _ROOT)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        for referenced in sorted(set(_iter_text_paths(text))):
            if referenced.split("/", 1)[0] in IGNORED_ROOTS:
                continue
            if not os.path.exists(os.path.join(_ROOT, referenced)):
                problems.append(f"{rel_doc}: 引用的路径不存在：{referenced}")
    return problems


def _readme_tree_block() -> list[str]:
    readme = os.path.join(_ROOT, "README.md")
    with open(readme, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == TREE_HEADING)
    except StopIteration:
        return []
    in_block = False
    block: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("```"):
            if in_block:
                break
            in_block = True
            continue
        if in_block:
            block.append(line)
    return block


def check_readme_tree() -> list[str]:
    problems: list[str] = []
    stack: list[tuple[int, str]] = []
    for line in _readme_tree_block():
        if not line.strip():
            continue
        match = TREE_ENTRY_RE.match(line)
        if not match:
            continue
        indent = len(match.group(1))
        name = match.group(2).rstrip("/")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else ""
        rel_path = f"{parent}{name}" if parent.endswith(("/", "")) else f"{parent}/{name}"
        rel_path = rel_path.lstrip("/")
        if rel_path.split("/", 1)[0] in IGNORED_ROOTS:
            continue
        full = os.path.join(_ROOT, rel_path)
        if not os.path.exists(full):
            problems.append(f"README 仓库结构：条目不存在：{rel_path}")
            continue
        if os.path.isdir(full):
            stack.append((indent, rel_path + "/"))
    return problems


def check_entry_points() -> list[str]:
    return [
        f"运行入口缺失：{entry}"
        for entry in ENTRY_POINTS
        if not os.path.exists(os.path.join(_ROOT, entry))
    ]


def main() -> int:
    problems = check_referenced_paths() + check_readme_tree() + check_entry_points()
    if problems:
        print(f"文档/仓库结构检查失败（{len(problems)} 项）：")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"文档/仓库结构检查通过：{len(_markdown_files())} 份 Markdown + 运行入口")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
