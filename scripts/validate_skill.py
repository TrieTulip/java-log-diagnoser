#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_skill.py —— java-log-diagnoser 的自检脚本。

检查 8 项，覆盖"结构完整"和"内容不说谎"两类问题：

1. SKILL.md frontmatter 合法（--- 分隔、name/description 齐全、name 与目录名一致）
2. 必需文件齐全
3. SKILL.md 中引用的仓库内路径真实存在
4. references 的 #anchor 可以被解析（避免知识库链接失效）
5. scripts/parse_java_log.py 语法正确
6. 脚本能在示例日志上跑通，且 JSON 含关键字段
7. 示例文档里的 L<行号> 不超出日志总行数（行号不编造）
8. 无 TODO / FIXME 残留

用法：
    python3 scripts/validate_skill.py          # 人类可读
    python3 scripts/validate_skill.py --quiet  # 只输出失败项

退出码：0 全部通过；1 存在失败项
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = "java-log-diagnoser"

REQUIRED_FILES = (
    "SKILL.md",
    "README.md",
    "LICENSE",
    "prompts/extract_root_cause.md",
    "prompts/generate_report.md",
    "scripts/parse_java_log.py",
    "references/java-exceptions.md",
    "references/safe-commands.md",
    "examples/README.md",
    "examples/npe-in-commit-chain.md",
    "examples/logs/npe-in-commit-chain.log",
    "examples/parsed/npe-in-commit-chain.json",
    "examples/reports/npe-in-commit-chain.report.md",
)

TRIGGER_KEYWORDS = ("NullPointerException", "OutOfMemoryError", "日志", "堆栈", "异常")

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> bool:
    results.append((ok, label))
    return ok


# --------------------------------------------------------------------------
# 1. frontmatter
# --------------------------------------------------------------------------
def parse_front_matter(text: str):
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    meta = {}
    for line in block.splitlines():
        if not line.strip() or line.startswith((" ", "\t", "#")):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("'\"")
    return meta


def check_frontmatter(quiet: bool):
    path = ROOT / "SKILL.md"
    if not check(path.exists(), "SKILL.md 存在"):
        return
    text = path.read_text(encoding="utf-8")
    meta = parse_front_matter(text)
    if not check(meta is not None, "SKILL.md 含合法 YAML frontmatter"):
        return
    name = meta.get("name", "")
    desc = meta.get("description", "")
    check(name == SKILL_NAME, f"frontmatter name = {name}（应与目录名一致）")
    check(bool(desc), "frontmatter 含 description")
    check(len(desc) <= 1024, f"description 长度 {len(desc)} ≤ 1024")
    hits = [k for k in TRIGGER_KEYWORDS if k in desc]
    check(len(hits) >= 2, f"description 含触发关键词 {hits}")
    check("工作流" in text or "四件套" in text, "SKILL.md 说明了工作流")
    check("强约束" in text, "SKILL.md 声明了强约束")


# --------------------------------------------------------------------------
# 2. 必需文件
# --------------------------------------------------------------------------
def check_files(quiet: bool):
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).exists()]
    check(not missing, f"必需文件齐全（{len(REQUIRED_FILES) - len(missing)}/{len(REQUIRED_FILES)}）"
                       + (f"，缺：{missing}" if missing else ""))


# --------------------------------------------------------------------------
# 3. SKILL.md 中的路径引用
# --------------------------------------------------------------------------
PATH_RE = re.compile(r"`([a-zA-Z0-9_][a-zA-Z0-9_./-]*\.(?:md|py|json|log))`")


def check_referenced_paths(quiet: bool):
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    bad = []
    seen = 0
    for ref in set(PATH_RE.findall(text)):
        if not ref.split("/")[0] in ("scripts", "prompts", "references", "examples"):
            continue
        seen += 1
        if not (ROOT / ref).exists():
            bad.append(ref)
    check(not bad, f"SKILL.md 引用的 {seen} 个仓库内路径均存在" + (f"，失效：{bad}" if bad else ""))


# --------------------------------------------------------------------------
# 4. references 锚点
# --------------------------------------------------------------------------
ANCHOR_DEF_RE = re.compile(r'<a id="([\w-]+)"></a>')
ANCHOR_REF_RE = re.compile(r"references/([\w.-]+\.md)#([\w-]+)")


def check_anchors(quiet: bool):
    anchors = {}
    for md in (ROOT / "references").glob("*.md"):
        anchors[md.name] = set(ANCHOR_DEF_RE.findall(md.read_text(encoding="utf-8")))
    bad = []
    total = 0
    for md in ROOT.rglob("*.md"):
        if ".git" in md.parts:
            continue
        for fname, anchor in ANCHOR_REF_RE.findall(md.read_text(encoding="utf-8")):
            total += 1
            if anchor not in anchors.get(fname, set()):
                bad.append(f"{md.relative_to(ROOT)} -> {fname}#{anchor}")
    check(not bad, f"references 锚点引用 {total} 处均可解析" + (f"，失效：{bad}" if bad else ""))


# --------------------------------------------------------------------------
# 5 & 6. 脚本
# --------------------------------------------------------------------------
def check_script(quiet: bool):
    script = ROOT / "scripts" / "parse_java_log.py"
    if not check(script.exists(), "parse_java_log.py 存在"):
        return
    try:
        compile(script.read_text(encoding="utf-8"), str(script), "exec")
        check(True, "parse_java_log.py 语法正确")
    except SyntaxError as exc:
        check(False, f"parse_java_log.py 语法错误：{exc}")
        return

    log = ROOT / "examples" / "logs" / "npe-in-commit-chain.log"
    if not log.exists():
        check(False, "示例日志缺失，无法验证脚本运行")
        return
    proc = subprocess.run(
        [sys.executable, str(script), "--file", str(log), "--app-package", "com.acme", "--compact"],
        capture_output=True,
    )
    if proc.returncode != 0:
        check(False, f"脚本运行失败：{proc.stderr.decode('utf-8', 'replace')[:200]}")
        return
    try:
        data = json.loads(proc.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        check(False, f"脚本输出不是合法 JSON：{exc}")
        return

    required_keys = {"schema_version", "summary", "chains", "business_frames", "signals", "warnings"}
    missing = required_keys - set(data)
    check(not missing, "输出 JSON 含全部关键字段" + (f"，缺：{missing}" if missing else ""))
    check(data["summary"]["chain_count"] >= 1 and data["summary"]["root_cause_type"] is not None,
          f"示例主链可解析（root_cause_type={data['summary'].get('root_cause_type')}）")
    check(len(data["business_frames"]) >= 1, f"示例识别出 {len(data['business_frames'])} 个业务帧")


# --------------------------------------------------------------------------
# 6.5 prompts 结构
# --------------------------------------------------------------------------
PROMPT_TOKENS = {
    "prompts/extract_root_cause.md": ("INSUFFICIENT_INFO", "confidence", "counter_evidence"),
    "prompts/generate_report.md": ("结论摘要", "分析边界", "止血", "待确认"),
}


def check_prompts(quiet: bool):
    bad = []
    for rel, tokens in PROMPT_TOKENS.items():
        path = ROOT / rel
        if not path.exists():
            bad.append(f"{rel} 缺失")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [t for t in tokens if t not in text]
        if missing:
            bad.append(f"{rel} 缺 {missing}")
    check(not bad, "prompts 含必需结构（降级分支 / 字段 / 固定章节）" + (f"，问题：{bad}" if bad else ""))


# --------------------------------------------------------------------------
# 7. 行号不越界
# --------------------------------------------------------------------------
LINE_REF_RE = re.compile(r"\bL(\d{1,6})\b")


def check_line_refs(quiet: bool):
    total = 0
    bad = []
    for md in (ROOT / "examples").rglob("*.md"):
        stem = md.stem
        if md.parent.name == "reports" and stem.endswith(".report"):
            stem = stem[: -len(".report")]
        log = ROOT / "examples" / "logs" / f"{stem}.log"
        if not log.exists():
            continue  # 索引文件，不对应具体日志
        line_count = len(log.read_text(encoding="utf-8").splitlines())
        for num in LINE_REF_RE.findall(md.read_text(encoding="utf-8")):
            total += 1
            if int(num) > line_count:
                bad.append(f"{md.name}: L{num} > {line_count} 行")
    check(not bad, f"示例中 {total} 处行号引用均未越界" + (f"，越界：{bad}" if bad else ""))


# --------------------------------------------------------------------------
# 8. 占位符残留
# --------------------------------------------------------------------------
def check_placeholders(quiet: bool):
    bad = []
    for md in ROOT.rglob("*.md"):
        if ".git" in md.parts:
            continue
        text = md.read_text(encoding="utf-8")
        for token in ("TODO", "FIXME", "XXX"):
            if token in text:
                bad.append(f"{md.relative_to(ROOT)}: {token}")
    check(not bad, "无 TODO/FIXME 残留" + (f"，发现：{bad}" if bad else ""))


# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="校验 java-log-diagnoser 的结构与内容一致性")
    ap.add_argument("--quiet", action="store_true", help="只输出失败项")
    args = ap.parse_args(argv)

    print(f"校验 {SKILL_NAME} @ {ROOT}\n")
    check_frontmatter(args.quiet)
    check_files(args.quiet)
    check_referenced_paths(args.quiet)
    check_anchors(args.quiet)
    check_script(args.quiet)
    check_prompts(args.quiet)
    check_line_refs(args.quiet)
    check_placeholders(args.quiet)

    for ok, label in results:
        if ok and args.quiet:
            continue
        print(f"[{' OK ' if ok else 'FAIL'}] {label}")

    passed = sum(1 for ok, _ in results if ok)
    failed = len(results) - passed
    print(f"\n结果：{passed} 通过 / {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
