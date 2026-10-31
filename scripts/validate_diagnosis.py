#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_diagnosis.py —— 报告与日志的硬校验（幻觉拦截器）。

为什么需要它：
  `prompts/` 里的"不许编造"只是文字约束，模型仍可能写出日志里根本不存在的
  `OrderService.java:999`、`GhostException`、`L42`。本脚本把这些**硬事实**抽出来，
  逐条回到原始日志做字符串级核对：对不上就退出码 1，报告不能交付。

与"肉眼审查"的分工：
  - 机器负责**可判定**的部分：这个类名/行号/原文到底在不在日志里；
  - 人（或 `prompts/validate_report.md`）负责**需判断**的部分：这条证据够不够支撑结论。

检查项：
  V1 [错误] 源码位置 `Foo.java:52` 必须在日志（或 parsed.json）中有同名同号的帧
  V2 [错误] **断言语境**下的异常类名必须真实出现在日志中
  V3 [错误] 日志行号 `L<n>` 必须落在真实行上，且该行非空
  V4 [错误] 证据表 `| E1 | L9 | `原文` |` 的引用必须与 L9 那一行逐字一致
  V5 [错误] 全限定类名 `com.x.Y` 必须能在日志中找到（支持 Spring 包名缩写还原）
  W2 [提示] 非"示意"代码块里出现日志中没有的堆栈帧
  W3 [提示] 非降级报告没有证据表
  N1 [信息] 否定/反事实语境提到日志中不存在的异常（"日志无 X"/"若是…会是 X"）

为什么不能只做 `if "Foo.java:52" not in log: error`：
  1. 日志里大量类名是缩写（`c.a.o.c.OrderController`），直接比对会把正常的还原判成幻觉；
  2. 报告必然要写"已排除 `SQLException`""若依赖没打进包，异常会是 `NoClassDefFoundError`"，
     这些名字本来就**不该**出现在日志里，一刀切会把正确报告判死；
  3. 证据引用可能带 `…` 省略，逐字比对要考虑片段；
  4. `-XX:+HeapDumpOnOutOfMemoryError` 是 JVM 参数，不是异常类名。
  这四条是"校验通不过"的主要来源，因此本脚本按**语境**分流，而不是按字符串分流。

用法：
    python3 scripts/validate_diagnosis.py --log app.log --report report.md
    python3 scripts/validate_diagnosis.py --log app.log --report report.md \\
        --parsed parsed.json --verbose
    python3 scripts/validate_diagnosis.py app.log report.md --json     # 位置参数亦可
    cat app.log | python3 scripts/validate_diagnosis.py --log - --report report.md

退出码：0 通过（可能带提示）；1 存在错误；2 无法执行（文件缺失 / 日志为空 / 参数错误）
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# 正则与常量
# --------------------------------------------------------------------------
# 源码位置：OrderAssembler.java:52 / OrderAssembler.java:41-60
# 范围只校验起点——"去读 41–60 行"里 60 是阅读范围，不是某条堆栈帧。
SRC_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_$\\/])([A-Z][\w$]*\.java):(\d{1,6})(?:\s*[-–—~至]\s*(\d{1,6}))?"
)

# 异常类名：只认 `FooException` / `FooError` / `FooThrowable` 形态。
# 前面排除 `.`，全限定名交给 V5 查，避免同一个问题报两遍。
EXC_RE = re.compile(r"(?<![\w$.])([A-Z][A-Za-z0-9_]*(?:Exception|Error|Throwable))(?![A-Za-z0-9_])")

# 全限定类名：至少一个包段 + 大写类名（可带内部类）
FQCN_RE = re.compile(r"(?<![\w$.])(?:[a-z][\w$]*\.)+[A-Z][\w$]*(?:\.[A-Z][\w$]*)*")

# 日志行号：L9、E1/L21；排除 L1 缓存这类单词粘连
LINE_REF_RE = re.compile(r"(?<![A-Za-z0-9_])L(\d{1,6})(?!\d)")

# 证据表行：| E1 | L9 | `原文` | ...
E_ROW_RE = re.compile(r"^\|\s*E(\d+)\s*\|\s*L(\d{1,6})\s*\|\s*`([^`]+)`")

# 堆栈帧：at com.x.Y.m(Y.java:12) / at java.base/java.lang.Thread.run(Thread.java:833)
FRAME_RE = re.compile(
    r"^\s*at\s+[\w.$/<>]+\(([\w$]+\.java)(?::(\d{1,6}))?\)\s*$"
)

# 代码块里出现这些字样，说明是示意代码，其中的行号/类名不参与硬校验
ILLUSTRATIVE_MARKS = ("示意", "伪代码", "以实际代码为准", "占位")

# 语境词：先否定、后反事实。顺序有意义——"没有 X，若…会是 Y" 要分别归类。
NEGATORS = ("无", "未", "没有", "不含", "不是", "并非", "排除", "未见",
            "不存在", "尚未", "不会")
# 否定后置：名字后面紧跟这些词，说明它本身是被排除的对象
NEGATED_SUFFIX = ("无关", "未出现", "没有出现", "不存在", "不会是", "并非")
HYPOTHETICALS = ("若", "如果", "假设", "假如", "倘若", "会是", "应为",
                 "预期", "可能", "或将", "将抛", "应该", "理论上")

# 小句边界：逗号也切，否则"日志里没有的类 A，异常 B 触发"会把 B 一起算成否定语境
CLAUSE_STOPS = ("。", "；", ";", "\n", "，", ",", "但", "不过", "然而", "而是")

# 降级报告的标志：这类报告本来就没有证据表，不该被 W3 误判
DEGRADED_MARKS = ("信息不足，拒绝盲目诊断", "业务包信息缺失，无法定位具体代码行")

MAX_EXCERPT = 120
MAX_SHOWN = 40


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------
@dataclass
class Finding:
    code: str
    severity: str          # error / warn / info
    message: str
    line_no: int = 0       # 报告中的行号
    excerpt: str = ""      # 报告原文摘录
    hint: str = ""         # 怎么改

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "report_line": self.line_no,
            "excerpt": self.excerpt,
            "hint": self.hint,
        }


@dataclass
class Result:
    errors: List[Finding] = field(default_factory=list)
    warnings: List[Finding] = field(default_factory=list)
    notes: List[Finding] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)
    report_lines: int = 0
    log_lines: int = 0
    log_path: str = ""
    report_path: str = ""
    parsed_path: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "log": self.log_path,
            "report": self.report_path,
            "parsed": self.parsed_path,
            "stats": self.stats,
            "errors": [f.as_dict() for f in self.errors],
            "warnings": [f.as_dict() for f in self.warnings],
            "notes": [f.as_dict() for f in self.notes],
        }


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def _norm(text: str) -> str:
    """空白归一：制表符、连续空格、全角空格都折成一个空格，再去首尾。"""
    return re.sub(r"[ \t\u3000]+", " ", text).strip()


def _excerpt(line: str) -> str:
    line = line.strip()
    return line if len(line) <= MAX_EXCERPT else line[: MAX_EXCERPT - 1] + "…"


def _iter_report_lines(text: str) -> List[Tuple[int, str, bool, bool]]:
    """返回 [(行号, 原文, 是否在代码块内, 是否示意代码块)]。

    代码块单独识别，是因为修复建议里的示例代码可以出现日志中没有的写法；
    但只要块内没有"示意"字样，它就仍是一条关于真实堆栈/真实代码的声明，照样要查。
    """
    lines = text.splitlines()
    out: List[Tuple[int, str, bool, bool]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].lstrip().startswith("```"):
                j += 1
            block = "\n".join(lines[i + 1: j])
            illustrative = any(mark in block for mark in ILLUSTRATIVE_MARKS)
            for k in range(i, min(j + 1, len(lines))):
                out.append((k + 1, lines[k], True, illustrative))
            i = j + 1
            continue
        out.append((i + 1, line, False, False))
        i += 1
    return out


def _clause_prefix(text: str, pos: int) -> str:
    """取 pos 所在小句的开头到 pos 之间的文字，用于判断语气。

    在句号/分号/逗号/转折词处切分，但**不切顿号**：
    "日志无 `SQLException`、`HikariPool`" 是一个整体，几个名字都该被否定语气覆盖。
    逗号必须切——否则前半句的"没有"会污染后半句的断言。
    """
    start = 0
    for stop in CLAUSE_STOPS:
        idx = text.rfind(stop, 0, pos)
        if idx != -1:
            start = max(start, idx + len(stop))
    return text[start:pos]


def _classify_mention(text: str, start: int, end: int) -> str:
    """把一次提及分为 config / negated / hypothetical / asserted。

    只有 asserted 才要求"必须在日志里出现"。分类错了的代价是放过一条幻觉，
    而一刀切的代价是正确报告被判死——后者会让工具直接被弃用。
    """
    # 1) JVM 参数：`-XX:+HeapDumpOnOutOfMemoryError`
    bt_open = text.rfind("`", 0, start)
    if bt_open != -1:
        bt_close = text.find("`", end)
        span = text[bt_open + 1: bt_close if bt_close != -1 else end]
        if span.strip().startswith("-X"):
            return "config"

    prefix = _clause_prefix(text, start)
    if any(tok in prefix for tok in NEGATORS):
        return "negated"
    # 2) 否定后置："X 与本故障无关""X 未在日志中出现"
    tail = text[end: end + 16]
    if any(tok in tail for tok in NEGATED_SUFFIX):
        return "negated"
    if any(tok in prefix for tok in HYPOTHETICALS):
        return "hypothetical"
    return "asserted"


def _abbrev_ok(report_name: str, token: str) -> bool:
    """判断 report_name 是否只是 token 的"包名展开"。

    日志（Logback 默认）会把 `com.acme.order.controller.OrderController` 缩成
    `c.a.o.c.OrderController`。规则与 prompts/validate_report.md 的 R1 一致：
    段数相同、类名相同、每个包段以缩写段开头。`c`→`com` ✅，`c`→`client` ❌。
    """
    rs, ts = report_name.split("."), token.split(".")
    if len(rs) != len(ts) or rs[-1] != ts[-1]:
        return False
    return all(t and r.startswith(t) for r, t in zip(rs[:-1], ts[:-1]))


# --------------------------------------------------------------------------
# 事实库：日志 + parsed.json
# --------------------------------------------------------------------------
class Corpus:
    def __init__(self, log_text: str, parsed_text: str = "") -> None:
        self.log_text = log_text
        self.text = log_text + "\n" + parsed_text
        self.frames: Dict[str, List[int]] = {}
        for file, num in re.findall(r"([A-Z][\w$]*\.java):(\d{1,6})", self.text):
            bucket = self.frames.setdefault(file, [])
            if int(num) not in bucket:
                bucket.append(int(num))
        for nums in self.frames.values():
            nums.sort()
        self.tokens = set(FQCN_RE.findall(self.text))
        self.exceptions = set(
            re.findall(r"(?<![\w$])[A-Z][\w$]*(?:Exception|Error|Throwable)(?![\w$])", self.text)
        )
        self._cache: Dict[str, bool] = {}

    def has_frame(self, file: str, line: str) -> bool:
        return f"{file}:{line}" in self.text

    def has_class(self, name: str) -> bool:
        if name in self.text:
            return True
        if name not in self._cache:
            self._cache[name] = any(_abbrev_ok(name, tok) for tok in self.tokens)
        return self._cache[name]


# --------------------------------------------------------------------------
# V1 源码位置
# --------------------------------------------------------------------------
def _check_source_refs(ctx, res: Result) -> None:
    for line_no, line, in_fence, illustrative in ctx.lines:
        if illustrative:
            continue
        for m in SRC_REF_RE.finditer(line):
            file, num = m.group(1), m.group(2)
            res.stats["src_refs"] += 1
            if ctx.corpus.has_frame(file, num):
                continue
            known = ctx.corpus.frames.get(file, [])
            if known:
                hint = (f"日志里 {file} 只出现于 " + "、".join(f":{n}" for n in known[:5]) +
                        "；改用真实帧，或删掉行号只写类名")
            else:
                hint = f"日志里没有任何 {file} 的堆栈帧；删掉这个位置，或改为日志中真实出现的类"
            res.errors.append(Finding(
                "V1", "error",
                f"幽灵源码位置：{file}:{num} 在日志与 parsed.json 中都没有对应帧",
                line_no, _excerpt(line), hint,
            ))


# --------------------------------------------------------------------------
# V2 异常类名（按语境分流）
# --------------------------------------------------------------------------
def _check_exceptions(ctx, res: Result) -> None:
    for line_no, line, in_fence, illustrative in ctx.lines:
        if illustrative:
            continue
        for m in EXC_RE.finditer(line):
            name = m.group(1)
            kind = _classify_mention(line, m.start(1), m.end(1))
            if kind == "config":
                continue
            res.stats["exceptions"] += 1
            if name in ctx.corpus.text:
                continue
            if kind == "asserted":
                pool = sorted(ctx.corpus.exceptions)[:6]
                hint = ("日志里出现过的异常：" + "、".join(pool)) if pool else \
                    "日志里没有解析到任何异常类型，不要点名具体异常"
                res.errors.append(Finding(
                    "V2", "error",
                    f"幽灵异常类型：报告中断言了 {name}，但日志里没有这个异常",
                    line_no, _excerpt(line), hint,
                ))
            else:
                res.notes.append(Finding(
                    "N1", "info",
                    f"{name} 未出现在日志中，此处语气为"
                    f"{'否定/排除' if kind == 'negated' else '假设/反事实'}，按已排除处理",
                    line_no, _excerpt(line),
                    "若确属排除项可忽略；若本意是断言，请补日志依据",
                ))


# --------------------------------------------------------------------------
# V3 日志行号
# --------------------------------------------------------------------------
def _check_line_refs(ctx, res: Result) -> None:
    total = res.log_lines
    for line_no, line, in_fence, illustrative in ctx.lines:
        if illustrative:
            continue
        for num in LINE_REF_RE.findall(line):
            n = int(num)
            res.stats["line_refs"] += 1
            if n < 1 or n > total:
                res.errors.append(Finding(
                    "V3", "error",
                    f"行号越界：L{n} 超出日志范围（共 {total} 行）",
                    line_no, _excerpt(line),
                    "改用日志中真实存在的行号；跨文件引用请注明文件名",
                ))
            elif not ctx.log_lines[n - 1].strip():
                res.errors.append(Finding(
                    "V3", "error",
                    f"行号落空：L{n} 是空行，不能作为证据出处",
                    line_no, _excerpt(line),
                    "改指到该证据真正所在的行",
                ))


# --------------------------------------------------------------------------
# V4 证据引用逐字比对
# --------------------------------------------------------------------------
def _quote_fragments(quote: str) -> List[str]:
    """按 `…` 拆分片段：省略号两侧都必须是原文，只核能核的部分。"""
    frags = []
    for part in re.split(r"…|\.\.\.|⋯", quote):
        part = _norm(part)
        if len(part) >= 4:
            frags.append(part)
    return frags


def _check_quotes(ctx, res: Result) -> None:
    total = res.log_lines
    seen_rows = 0
    for line_no, line, in_fence, illustrative in ctx.lines:
        if illustrative:
            continue
        m = E_ROW_RE.match(line.strip())
        if not m:
            continue
        seen_rows += 1
        res.stats["quotes"] += 1
        eid, num, quote = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= num <= total):
            continue  # 交给 V3 报，避免同一处出两条
        frags = _quote_fragments(quote)
        if not frags:
            continue
        src = _norm(ctx.log_lines[num - 1])
        if all(frag in src for frag in frags):
            continue
        missing = next(frag for frag in frags if frag not in src)
        res.errors.append(Finding(
            "V4", "error",
            f"证据引用与日志不一致：E{eid} 声称引用 L{num}，但该行没有「{_excerpt(missing)}」",
            line_no, _excerpt(line),
            f"L{num} 原文：{_excerpt(ctx.log_lines[num - 1])}；逐字照抄，或在省略处用 `…` 断开",
        ))
    if seen_rows == 0:
        text = "\n".join(l for _, l, _, _ in ctx.lines)
        if not any(mark in text for mark in DEGRADED_MARKS):
            res.warnings.append(Finding(
                "W3", "warn",
                "报告没有证据表（`| E<n> | L<n> | `原文` |`），结论无法逐条回溯",
                0, "", "补第 2 节证据表；信息不足时改用降级模板",
            ))


# --------------------------------------------------------------------------
# V5 全限定类名
# --------------------------------------------------------------------------
def _check_classes(ctx, res: Result) -> None:
    for line_no, line, in_fence, illustrative in ctx.lines:
        if illustrative:
            continue
        for name in FQCN_RE.findall(line):
            res.stats["classes"] += 1
            if ctx.corpus.has_class(name):
                continue
            res.errors.append(Finding(
                "V5", "error",
                f"幽灵类名：{name} 在日志与 parsed.json 中都找不到",
                line_no, _excerpt(line),
                "删掉该类名，或改为日志中真实出现的类；日志用缩写名时，展开后需注明「日志中为缩写形式」",
            ))


# --------------------------------------------------------------------------
# W2 代码块里的堆栈帧
# --------------------------------------------------------------------------
def _check_fence_frames(ctx, res: Result) -> None:
    reported = set()
    for line_no, line, in_fence, illustrative in ctx.lines:
        if not in_fence or illustrative:
            continue
        m = FRAME_RE.match(line)
        if not m:
            continue
        raw = _norm(line)
        if raw in ctx.corpus.text or raw in reported:
            continue
        reported.add(raw)
        res.warnings.append(Finding(
            "W2", "warn",
            "代码块里出现了日志中没有的堆栈帧，容易被误读为原始日志",
            line_no, _excerpt(line),
            "把这段标成「示意」（块内写 // 示意），或换成日志中的真实帧",
        ))


# --------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------
class _Ctx:
    def __init__(self, log_text: str, report_text: str, parsed_text: str) -> None:
        self.log_lines = log_text.splitlines()
        self.lines = _iter_report_lines(report_text)
        self.corpus = Corpus(log_text, parsed_text)


def validate(log_text: str, ai_report: str, parsed_text: str = "",
             strict: bool = False) -> Result:
    """校验一份报告，返回 Result。纯函数，不读文件、不打印。

    `log_text` 是唯一事实来源；`parsed_text` 是 parse_java_log.py 的输出，
    用于给缩写类名、行号提供第二来源（可选，但强烈建议给）。
    """
    ctx = _Ctx(log_text, ai_report, parsed_text)
    res = Result(
        stats={"src_refs": 0, "exceptions": 0, "line_refs": 0, "quotes": 0, "classes": 0},
        report_lines=len(ai_report.splitlines()),
        log_lines=len(ctx.log_lines),
    )
    _check_source_refs(ctx, res)
    _check_exceptions(ctx, res)
    _check_line_refs(ctx, res)
    _check_quotes(ctx, res)
    _check_classes(ctx, res)
    _check_fence_frames(ctx, res)

    if strict and res.warnings:
        res.errors.extend(res.warnings)
        res.warnings = []

    order = {"V1": 1, "V2": 2, "V3": 3, "V4": 4, "V5": 5, "W2": 6, "W3": 7, "N1": 8}
    for bucket in (res.errors, res.warnings, res.notes):
        bucket.sort(key=lambda f: (f.line_no, order.get(f.code, 99)))
    return res


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------
def _symbol(preferred: str, fallback: str) -> str:
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        preferred.encode(enc)
        return preferred
    except Exception:
        return fallback


OK = _symbol("✅", "[OK]")
BAD = _symbol("❌", "[X]")
WARN = _symbol("⚠️", "!")
TIP = _symbol("·", "-")


def _print_finding(f: Finding, verbose: bool) -> None:
    if f.severity == "error":
        head = f"{BAD} {f.code} {f.message}"
    elif f.severity == "warn":
        head = f"{WARN} {f.code} {f.message}"
    else:
        head = f"{TIP} {f.code} {f.message}"
    print(head)
    if f.line_no:
        print(f"   报告第 {f.line_no} 行：{f.excerpt}")
    elif f.excerpt:
        print(f"   {f.excerpt}")
    if f.hint and (verbose or f.severity == "error"):
        print(f"   修法：{f.hint}")


def print_human(res: Result, verbose: bool = False, quiet: bool = False) -> None:
    if not quiet:
        print("java-log-diagnoser · 报告硬校验")
        print(f"报告：{res.report_path or '<stdin>'}（{res.report_lines} 行）")
        print(f"日志：{res.log_path or '<stdin>'}（{res.log_lines} 行）")
        print(f"基准：日志" + (f" + {res.parsed_path}" if res.parsed_path else "（未提供 parsed.json）"))
        print()

    shown = 0
    for f in res.errors:
        if shown >= MAX_SHOWN:
            print(f"{BAD} …… 还有 {len(res.errors) - MAX_SHOWN} 处错误未逐条列出")
            break
        _print_finding(f, verbose)
        shown += 1
    for f in res.warnings:
        _print_finding(f, verbose)
    if verbose:
        for f in res.notes:
            _print_finding(f, verbose)

    if res.errors:
        print()
        print(f"共 {len(res.errors)} 处错误" +
              (f"、{len(res.warnings)} 条提示" if res.warnings else ""))
        print(f"{WARN} 校验失败，请 AI 重新生成报告（或按上面的「修法」逐条修正）。")
        return

    if quiet:
        return

    print(f"{OK} 校验通过：" +
          f"{res.stats['src_refs']} 处源码位置、" +
          f"{res.stats['exceptions']} 个异常类名、" +
          f"{res.stats['line_refs']} 处 L 号、" +
          f"{res.stats['quotes']} 条证据引用、" +
          f"{res.stats['classes']} 个类名，均可在日志中找到。")
    if res.notes and not verbose:
        print(f"   {len(res.notes)} 处否定/假设语境的异常提及已跳过，加 --verbose 查看。")
    if res.warnings:
        print(f"   {len(res.warnings)} 条提示未阻断，建议按提示收敛。")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="校验诊断报告里的类名/行号/证据引用是否真的存在于日志中",
        epilog="退出码：0 通过；1 有错误；2 无法执行",
    )
    ap.add_argument("paths", nargs="*", metavar="LOG REPORT",
                    help="位置参数：日志文件、报告文件（等价于 --log/--report）")
    ap.add_argument("-l", "--log", help="原始日志路径，`-` 表示标准输入")
    ap.add_argument("-r", "--report", help="待校验的报告路径")
    ap.add_argument("-p", "--parsed", help="parse_java_log.py 的输出 JSON（可选，提高缩写还原准确率）")
    ap.add_argument("--strict", action="store_true", help="把提示也当作错误")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--quiet", action="store_true", help="通过时静默，失败时只打错误")
    ap.add_argument("--verbose", action="store_true", help="输出提示与跳过的提及")
    args = ap.parse_args(argv)

    log_path = args.log or (args.paths[0] if len(args.paths) >= 1 else None)
    report_path = args.report or (args.paths[1] if len(args.paths) >= 2 else None)
    if not log_path or not report_path:
        ap.error("需要同时提供日志与报告：--log LOG --report REPORT")

    try:
        log_text = _read(log_path)
        report_text = _read(report_path)
        parsed_text = _read(args.parsed) if args.parsed else ""
    except OSError as exc:
        print(f"{BAD} 读取失败：{exc}", file=sys.stderr)
        return 2

    if not log_text.strip():
        print(f"{BAD} 日志为空，无法校验（报告里的每个事实都需要原文作基准）。", file=sys.stderr)
        return 2
    if not report_text.strip():
        print(f"{BAD} 报告为空，没有可校验的内容。", file=sys.stderr)
        return 2

    res = validate(log_text, report_text, parsed_text, strict=args.strict)
    res.log_path, res.report_path = log_path, report_path
    res.parsed_path = args.parsed or ""

    if args.json:
        print(json.dumps(res.as_dict(), ensure_ascii=False, indent=2))
    else:
        print_human(res, verbose=args.verbose, quiet=args.quiet)
    return 0 if res.ok else 1


if __name__ == "__main__":
    # 被管道/子进程调用时统一用 UTF-8，避免 Windows 上 cp936 编码失败；
    # 终端里保留原编码，符号打印有 fallback。
    if not sys.stdout.isatty():
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
