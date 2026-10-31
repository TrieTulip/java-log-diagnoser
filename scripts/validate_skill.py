#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_skill.py —— java-log-diagnoser 的严格自检。

设计原则：**能证明的才通过**。上一版只检查"键存在 / 文件存在"，因此以下问题都能混过去：
文档里的 JSON 是手写的、行号指向空行、parsed 快照早已过期、报告缺章节、
禁止命令被抄进命令表、示例只有一份却声称覆盖多场景。这一版逐条堵住。

五组检查：
  A 结构     frontmatter、必需文件、仓库内路径、锚点
  B 示例     四件套齐全、parsed 快照与当前脚本逐字段一致、行号指向真实非空行
  C 内容     报告七节/降级模板、[事实] 标注、反证、prompts 字段名真实存在
  D 安全     危险命令不得出现在可执行位置、无 TODO 残留、索引与实际示例一致
  E 审查     R1 类名/源码位置可回溯、R2 无绝对化断言、审查样例判定自洽
  F 硬校验   交付给用户的 validate_diagnosis.py 能在所有成品报告上跑通（真的执子进程）

用法：
    python3 scripts/validate_skill.py            # 人类可读
    python3 scripts/validate_skill.py --quiet    # 只输出失败项
    python3 scripts/validate_skill.py --verbose  # 额外输出 diff 细节

退出码：0 全部通过；1 存在失败项
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = "java-log-diagnoser"
EXAMPLES = ROOT / "examples"
SKIP_DIRS = {".git", ".workbuddy", "__pycache__", "node_modules", ".idea"}

REQUIRED_FILES = (
    "SKILL.md",
    "README.md",
    "LICENSE",
    "docs/USAGE.zh-CN.md",
    "prompts/extract_root_cause.md",
    "prompts/generate_report.md",
    "prompts/validate_report.md",
    "scripts/parse_java_log.py",
    "scripts/validate_diagnosis.py",
    "scripts/validate_skill.py",
    "scripts/mutation_test.py",
    "references/java-exceptions.md",
    "references/safe-commands.md",
    "examples/README.md",
)

# description 必须覆盖的触发词：覆盖用户的真实表述，而不只是异常类名
TRIGGER_KEYWORDS = (
    "NullPointerException", "OutOfMemoryError", "ClassNotFoundException", "NoSuchMethodError",
    "堆栈", "异常", "日志", "启动失败", "依赖冲突", "Connection refused",
)

results: list[tuple[bool, str]] = []
verbose = False


def check(ok: bool, label: str, detail: str = "") -> bool:
    results.append((ok, label + (f" —— {detail}" if detail and not ok else "")))
    if detail and not ok and verbose:
        for line in str(detail).splitlines()[:20]:
            results.append((False, f"    {line}"))
    return ok


def iter_md():
    for md in ROOT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in md.parts):
            continue
        yield md


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# A1. frontmatter
# --------------------------------------------------------------------------
def parse_front_matter(text: str):
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    meta = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.startswith((" ", "\t", "#")) or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("'\"")
    return meta


def check_frontmatter():
    path = ROOT / "SKILL.md"
    if not check(path.exists(), "SKILL.md 存在"):
        return
    text = read(path)
    meta = parse_front_matter(text)
    if not check(meta is not None, "SKILL.md 含合法 YAML frontmatter（--- 起始且闭合）"):
        return
    name, desc = meta.get("name", ""), meta.get("description", "")
    check(name == SKILL_NAME, f"frontmatter name = {SKILL_NAME}", f"实际为 {name!r}")
    check(len(desc) >= 120, "description 足够描述触发场景（≥120 字符）", f"仅 {len(desc)} 字符")
    check(len(desc) <= 1024, "description 未超长（≤1024 字符）", f"{len(desc)} 字符")
    missing = [k for k in TRIGGER_KEYWORDS if k not in desc]
    check(not missing, f"description 覆盖 {len(TRIGGER_KEYWORDS)} 个触发词", f"缺 {missing}")
    check("工作流" in text and "强约束" in text, "SKILL.md 含工作流与强约束两节")


# --------------------------------------------------------------------------
# A2. 必需文件 / A3. 仓库内路径 / A4. 锚点
# --------------------------------------------------------------------------
def check_files():
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).exists()]
    check(not missing, f"必需文件齐全（{len(REQUIRED_FILES)} 项）", f"缺 {missing}")


PATH_RE = re.compile(r"`([a-zA-Z0-9_][a-zA-Z0-9_./-]*\.(?:md|py|json|log))`")


def check_referenced_paths():
    text = read(ROOT / "SKILL.md")
    refs = [r for r in PATH_RE.findall(text)
            if r.split("/")[0] in ("scripts", "prompts", "references", "examples")]
    bad = [r for r in refs if not (ROOT / r).exists()]
    check(not bad, f"SKILL.md 引用的 {len(refs)} 个仓库内路径均存在", f"失效 {bad}")


ANCHOR_DEF_RE = re.compile(r'<a id="([\w-]+)"></a>\s*\n+#{2,6}\s+\S')
ANCHOR_REF_RE = re.compile(r"references/([\w.-]+\.md)#([\w-]+)")


def check_anchors():
    anchors, empty = {}, []
    for md in (ROOT / "references").glob("*.md"):
        text = read(md)
        anchors[md.name] = set(ANCHOR_DEF_RE.findall(text))
        # 定义了 <a id> 却没跟标题，锚点会落在空处
        for aid in re.findall(r'<a id="([\w-]+)"></a>', text):
            if aid not in anchors[md.name]:
                empty.append(f"{md.name}#{aid}")
    check(not empty, "references 的每个锚点都紧跟小节标题", f"落空 {empty}")

    bad, total = [], 0
    for md in iter_md():
        for fname, anchor in ANCHOR_REF_RE.findall(read(md)):
            total += 1
            if anchor not in anchors.get(fname, set()):
                bad.append(f"{md.relative_to(ROOT)} -> {fname}#{anchor}")
    check(not bad, f"锚点引用 {total} 处均可解析", f"失效 {bad}")


# --------------------------------------------------------------------------
# B 示例：四件套 + 快照一致 + 行号真实
# --------------------------------------------------------------------------
def discover_examples():
    return sorted(p.stem for p in (EXAMPLES / "logs").glob("*.log"))


def check_example_sets():
    names = discover_examples()
    if not check(len(names) >= 4, "示例数量 ≥4（覆盖不同失败模式）", f"仅 {len(names)} 个"):
        pass
    bad = []
    for n in names:
        for rel in (f"examples/{n}.md", f"examples/parsed/{n}.json", f"examples/reports/{n}.report.md"):
            if not (ROOT / rel).exists():
                bad.append(rel)
    check(not bad, f"{len(names)} 个示例均为四件套（log + 讲解 + parsed + report）", f"缺 {bad}")


def run_parser(log: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/parse_java_log.py"),
         "--file", str(log), "--app-package", "com.acme", "--compact"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:300])
    return json.loads(proc.stdout.decode("utf-8"))


def diff_json(a, b, path=""):
    """逐字段比较，忽略时间戳；返回可读差异列表。"""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: 快照缺失")
            elif key not in b:
                out.append(f"{path}.{key}: 快照多余")
            else:
                out += diff_json(a[key], b[key], f"{path}.{key}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: 长度 {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_json(x, y, f"{path}[{i}]")
    elif a != b:
        out.append(f"{path}: {a!r} != {b!r}")
    return out


def check_snapshots(live: dict):
    """parsed/*.json 必须等于当前脚本的输出。防止文档与脚本各说一套。"""
    bad = []
    for name, live_data in live.items():
        path = ROOT / f"examples/parsed/{name}.json"
        if not path.exists():
            bad.append(f"{name}: 快照文件缺失")
            continue
        snapshot = json.loads(read(path))
        snap_copy = json.loads(json.dumps(snapshot))
        live_copy = json.loads(json.dumps(live_data))
        for obj in (snap_copy, live_copy):
            obj.get("parser", {}).pop("generated_at", None)
        diffs = diff_json(live_copy, snap_copy)
        if diffs:
            bad.append(f"{name}: {len(diffs)} 处不一致，如 {diffs[0]}")
    check(not bad, f"{len(live)} 份 parsed 快照与脚本当前输出逐字段一致", "\n".join(bad))


def check_schema_version(live: dict):
    script = read(ROOT / "scripts/parse_java_log.py")
    m = re.search(r'SCHEMA_VERSION\s*=\s*"([\d.]+)"', script)
    if not check(bool(m), "脚本声明了 SCHEMA_VERSION"):
        return
    version = m.group(1)
    bad = [f"{n}: {d.get('schema_version')}" for n, d in live.items() if d.get("schema_version") != version]
    check(not bad, f"示例快照 schema_version 与脚本一致（{version}）", f"不一致 {bad}")


def check_root_line_truth(live: dict):
    """结论字段必须能在日志中核对：root_cause_log_line 那行要真的含该异常类型。"""
    bad = []
    for name, data in live.items():
        summary = data["summary"]
        line_no, exc = summary.get("root_cause_log_line"), summary.get("root_cause_type")
        if not line_no or not exc:
            continue
        lines = read(EXAMPLES / "logs" / f"{name}.log").splitlines()
        if not (1 <= line_no <= len(lines)):
            bad.append(f"{name}: L{line_no} 越界")
            continue
        simple = exc.rsplit(".", 1)[-1]
        if simple not in lines[line_no - 1]:
            bad.append(f"{name}: L{line_no} 不含 {simple}")
    check(not bad, "root_cause_log_line 指向的行确实包含该异常类型", f"{bad}")


LINE_REF_RE = re.compile(r"\bL(\d{1,6})\b")


def check_line_refs():
    """L<n> 必须落在真实行上，且该行非空。只查上界会让 L1 指向空行也通过。"""
    bad, total = [], 0
    for md in EXAMPLES.rglob("*.md"):
        stem = md.stem
        if md.parent.name == "reports" and stem.endswith(".report"):
            stem = stem[: -len(".report")]
        elif md.parent.name == "reviews" and stem.endswith(".review"):
            stem = stem[: -len(".review")]
        log = EXAMPLES / "logs" / f"{stem}.log"
        if not log.exists():
            continue
        lines = read(log).splitlines()
        for num in LINE_REF_RE.findall(read(md)):
            total += 1
            n = int(num)
            if n < 1 or n > len(lines):
                bad.append(f"{md.name}: L{n} 越界（共 {len(lines)} 行）")
            elif not lines[n - 1].strip():
                bad.append(f"{md.name}: L{n} 是空行")
    check(not bad, f"示例中 {total} 处 L<n> 均指向真实的非空行", f"{bad}")


def check_signal_self_consistency(live: dict):
    bad = []
    for name, data in live.items():
        summary, signals = data["summary"], data["signals"]
        computed = {s["name"] for s in signals if s.get("in_primary_chain")}
        if computed != set(summary.get("primary_signals", [])):
            bad.append(f"{name}: primary_signals 与 signals 不一致")
        for s in signals:
            if s.get("in_primary_chain") != any(e.get("in_primary_chain") for e in s["evidence"]):
                bad.append(f"{name}: {s['name']} 的 in_primary_chain 与证据不符")
    check(not bad, f"{len(live)} 份快照的信号归属自洽（primary/noise 划分正确）", f"{bad}")


# --------------------------------------------------------------------------
# C 内容：报告结构 / 字段名真实 / prompts
# --------------------------------------------------------------------------
DEGRADED_MARKS = ("信息不足，拒绝盲目诊断", "业务包信息缺失，无法定位具体代码行")
NO_FRAME_LITERAL = "【业务包信息缺失，无法定位具体代码行】"


def check_reports():
    bad = []
    reports = sorted((EXAMPLES / "reports").glob("*.report.md"))
    for rp in reports:
        text = read(rp)
        degraded = next((m for m in DEGRADED_MARKS if m in text), None)
        if degraded:
            need = ["## 1. 已知", "## 2. 为什么不够", "## 3. 需要你补充", "## 4. 你可以先做的只读检查"]
            missing = [s for s in need if s not in text]
            if missing:
                bad.append(f"{rp.name}: 降级模板缺 {missing}")
            if "## 3. 根因假设" in text or "## 4. 修复建议" in text:
                bad.append(f"{rp.name}: 降级报告不得输出假设与修复建议")
            if degraded == DEGRADED_MARKS[1] and NO_FRAME_LITERAL not in text:
                bad.append(f"{rp.name}: 业务包缺失报告必须原文写出 {NO_FRAME_LITERAL}")
            continue
        need = ["## 1. 结论摘要", "## 2. 关键证据", "## 3. 根因假设",
                "## 4. 修复建议", "## 6. 分析边界", "## 7. 待确认"]
        missing = [s for s in need if s not in text]
        if missing:
            bad.append(f"{rp.name}: 缺章节 {missing}")
        if "[事实]" not in text:
            bad.append(f"{rp.name}: 无 [事实] 标注")
        if "反证" not in text:
            bad.append(f"{rp.name}: 假设未写反证")
        if not re.search(r"置信度", text):
            bad.append(f"{rp.name}: 未标注置信度")
    check(not bad, f"{len(reports)} 份报告结构合规（七节 / 降级模板 / 标注）", "\n".join(bad))


FIELD_RE = re.compile(r"\b(summary|out_of_memory|parser|chains|business_frames|first_business_frame|"
                      r"root_business_frame|signals|exceptions|error_lines|warnings)\.([a-z_]+)\b")


def check_field_names(live: dict):
    """文档里引用的 summary.xxx 必须在真实输出中存在，否则模型会照抄一个不存在的字段。"""
    ref = live[discover_examples()[0]]
    known = {top: set(ref[top]) for top in ref if isinstance(ref[top], dict)}
    bad, total = [], 0
    for md in list(iter_md()) + [ROOT / "scripts/parse_java_log.py"]:
        text = read(md)
        for top, sub in FIELD_RE.findall(text):
            if top not in known:
                continue
            total += 1
            if sub not in known[top]:
                bad.append(f"{md.name}: {top}.{sub} 不存在")
    check(not bad, f"文档引用的 {total} 处 JSON 字段名均真实存在", f"{bad}")


# --------------------------------------------------------------------------
# C0. 红线与工作流门禁：写在开头的东西，也得有人看着它别被删掉
# --------------------------------------------------------------------------
RED_LINE_HEAD = "绝对红线"
# 比对用裸文案：报告标题写成「诊断报告：信息不足，拒绝盲目诊断」也算命中，
# 是否加【】是排版问题，不是规则问题。
DEGRADED_BANNER = "信息不足，拒绝盲目诊断"


def check_red_lines():
    text = read(ROOT / "SKILL.md")
    bad = []
    for token in ("Zero-Tolerance", "R1", "R2", "R3", "3 个具体问题", DEGRADED_BANNER):
        if token not in text:
            bad.append(f"SKILL.md 缺 {token}")
    pos_red, pos_first = text.find(RED_LINE_HEAD), text.find("## 1. 何时使用")
    if pos_red == -1:
        bad.append("SKILL.md 没有红线章节")
    elif pos_first != -1 and pos_red > pos_first:
        bad.append("红线章节必须位于文档开头（当前在“何时使用”之后）")
    check(not bad, "SKILL.md 开头有三条红线（R1–R3）且含拒诊标记", "\n".join(bad))

    bad = []
    for rel in ("prompts/generate_report.md", "prompts/extract_root_cause.md"):
        path = ROOT / rel
        if not path.exists() or DEGRADED_BANNER not in read(path):
            bad.append(f"{rel} 未使用 {DEGRADED_BANNER}")
    reports = sorted((EXAMPLES / "reports").glob("*.report.md"))
    if not any(DEGRADED_BANNER in read(p) for p in reports):
        bad.append(f"{len(reports)} 份报告里没有一份演示拒诊标记")
    check(not bad, f"拒诊标记在 prompts 与 {len(reports)} 份示例报告中口径一致", "\n".join(bad))


def check_workflow_gate():
    """Step 2 跑脚本、Step 4.2 过硬校验——顺序错了等于流程没执行。"""
    text = read(ROOT / "SKILL.md")
    heads = ["### Step 1 预处理", "### Step 2 脚本解析", "### Step 3 结合模板分析",
             "### Step 4 输出与自动拦截", "#### 4.2 强制硬校验"]
    idx = [text.find(h) for h in heads]
    bad = [f"缺 {h.lstrip('# ')}" for h, i in zip(heads, idx) if i == -1]
    found = [i for i in idx if i != -1]
    if found != sorted(found):
        bad.append("工作流步骤顺序错乱：预处理 → 脚本解析 → 模板分析 → 输出与拦截")
    check(not bad, "SKILL.md 工作流五步齐备且顺序正确", "\n".join(bad))

    tail = text[idx[3]:] if idx[3] != -1 else ""
    missing = [t for t in ("validate_diagnosis.py", "非 0 退出不得交付", "重跑")
               if t not in tail]
    check(not missing, "Step 4 内含强制硬校验门禁（脚本、退出码、改后重跑）", f"{missing}")


PROMPT_TOKENS = {
    "prompts/extract_root_cause.md": ("INSUFFICIENT_INFO", "confidence", "counter_evidence",
                                      "first_business_frame", "root_business_frame"),
    "prompts/generate_report.md": ("结论摘要", "分析边界", "止血", "待确认", "L<行号>"),
}


def check_prompts():
    bad = []
    for rel, tokens in PROMPT_TOKENS.items():
        path = ROOT / rel
        if not path.exists():
            bad.append(f"{rel} 缺失")
            continue
        text = read(path)
        missing = [t for t in tokens if t not in text]
        if missing:
            bad.append(f"{rel} 缺 {missing}")
    check(not bad, "prompts 含必需字段与固定章节", f"{bad}")


# --------------------------------------------------------------------------
# C2. 防幻觉门禁：prompts 规则存在 + 示例证据表逐字可核 + 假设闭环 + 自审
# --------------------------------------------------------------------------
GATE_TOKENS = {
    "prompts/extract_root_cause.md": (
        "防幻觉红牌", "证据链闭环", "输出前自我审查", "SELF_CHECK",
        "NO_BUSINESS_FRAME", "【业务包信息缺失，无法定位具体代码行】", "逐字一致",
    ),
    "prompts/generate_report.md": ("入口门禁", "SELF_CHECK", "NO_BUSINESS_FRAME"),
    "prompts/validate_report.md": (
        "只审不写", "幽灵事实", "绝对化措辞", "需补充的信息",
        "【审查通过】", "【审查失败及修改意见】", "REVIEW: PASS", "REVIEW: FAIL",
        "两轮",
    ),
}


def check_prompt_gates():
    bad = []
    for rel, tokens in GATE_TOKENS.items():
        path = ROOT / rel
        if not path.exists():
            bad.append(f"{rel} 缺失")
            continue
        text = read(path)
        missing = [t for t in tokens if t not in text]
        if missing:
            bad.append(f"{rel} 缺 {missing}")
    check(not bad, "prompts 含防幻觉红牌 / 证据链闭环 / 自审门禁", f"{bad}")


E_ROW_RE = re.compile(r"^E(\d+)\s*\|\s*L(\d+)\s*\|\s*>\s?(.*)$")
H_ROW_RE = re.compile(r"^H(\d+)\s*\|\s*confidence=(high|medium|low)\s*\|\s*(.+)$")
CITE_RE = re.compile(r"^-\s*(?:引用|依据)\s*[:：]\s*(.+)$")
E_ID_RE = re.compile(r"E(\d+)")


def split_hypotheses(text: str):
    """把 Step 3 输出切成 H1/H2/H3 块，块内保留原始行（已 strip）。"""
    blocks, cur = [], None
    for line in text.splitlines():
        s = line.strip()
        m = H_ROW_RE.match(s)
        if m:
            if cur:
                blocks.append(cur)
            cur = {"id": int(m.group(1)), "confidence": m.group(2), "body": []}
            continue
        if cur is not None and (s.startswith("### ") or s.startswith("## ")):
            blocks.append(cur)
            cur = None
            continue
        if cur is not None:
            cur["body"].append(s)
    if cur:
        blocks.append(cur)
    return blocks


def check_evidence_closure():
    """示例里的 E 表必须逐字等于日志原文；H 只能引用存在的 E；E 不得孤立；必须自审。"""
    bad, n_e, n_h = [], 0, 0
    for name in discover_examples():
        md, log = EXAMPLES / f"{name}.md", EXAMPLES / "logs" / f"{name}.log"
        if not md.exists() or not log.exists():
            continue
        text = read(md)
        if "### 5. 假设" not in text:
            continue  # 降级分支示例不产生假设，不要求证据表
        lines = read(log).splitlines()
        defined = {}
        for line in text.splitlines():
            m = E_ROW_RE.match(line.strip())
            if not m:
                continue
            eid, num, quote = int(m.group(1)), int(m.group(2)), m.group(3).strip()
            defined[eid] = quote
            n_e += 1
            if not (1 <= num <= len(lines)):
                bad.append(f"{name}: E{eid} 的 L{num} 越界（共 {len(lines)} 行）")
                continue
            src = lines[num - 1].strip()
            good = src.startswith(quote[:-1].rstrip()) if quote.endswith("…") else quote == src
            if not good:
                bad.append(f"{name}: E{eid} 的引用与 L{num} 原文不一致")
        if not defined:
            bad.append(f"{name}: 有假设但缺证据表")
            continue

        cited = set()
        for line in text.splitlines():
            if "引用:" in line or "依据:" in line or "依据：" in line:
                cited |= {int(x) for x in E_ID_RE.findall(line)}

        for h in split_hypotheses(text):
            n_h += 1
            cite = next((s for s in h["body"] if CITE_RE.match(s)), None)
            ids = {int(x) for x in E_ID_RE.findall(cite)} if cite else set()
            if not ids:
                bad.append(f"{name}: H{h['id']} 缺 '- 引用: E<n>'")
            ghost = ids - set(defined)
            if ghost:
                bad.append(f"{name}: H{h['id']} 引用了不存在的 E{sorted(ghost)}")
            if not any(s.startswith("- 推理链") for s in h["body"]):
                bad.append(f"{name}: H{h['id']} 缺推理链")
        orphan = set(defined) - cited
        if orphan:
            bad.append(f"{name}: E{sorted(orphan)} 未被任何假设/排除项引用")

        if not re.search(r"^SELF_CHECK:\s*(PASS|PASS_WITH_GAPS)\s*$", text, re.M):
            bad.append(f"{name}: 缺 SELF_CHECK: PASS / PASS_WITH_GAPS")
        if "### 8. 自我审查" not in text or len(re.findall(r"^\| \d+ \|", text, re.M)) < 6:
            bad.append(f"{name}: 自我审查表少于 6 行")
    check(not bad, f"{n_e} 条证据逐字可核 + {n_h} 条假设闭环并自审", "\n".join(bad))


def check_report_evidence_ids():
    """报告证据表的 E 编号必须是 Step 3 里定义过的，防止各处各编一套。"""
    bad = []
    for name in discover_examples():
        ex, rp = EXAMPLES / f"{name}.md", EXAMPLES / "reports" / f"{name}.report.md"
        if not ex.exists() or not rp.exists():
            continue
        defined = {int(x) for x in re.findall(r"^E(\d+)\s*\|", read(ex), re.M)}
        if not defined:
            continue
        used = {int(x) for x in re.findall(r"^\|\s*E(\d+)\s*\|", read(rp), re.M)}
        extra = sorted(used - defined)
        if extra:
            bad.append(f"{name}: 报告用了 Step 3 未定义的 E{extra}")
    check(not bad, "报告证据编号与 Step 3 证据表一致", f"{bad}")


# --------------------------------------------------------------------------
# C3. R1 幽灵事实：报告里的类名 / 源码位置必须能在日志或 JSON 中回溯
# --------------------------------------------------------------------------
FQCN_RE = re.compile(r"\b(?:[a-z][\w]*\.)+[A-Z][\w$]*(?:\.[A-Z][\w$]*)*")
SRC_REF_RE = re.compile(r"\b([A-Z][\w$]*\.java):(\d+)")
# 审查样例允许引用"问题初稿"里的编造类名，因此不参与本项（真实报告必须过）
REVIEW_DIR = "reviews"


def check_report_facts():
    """对应 validate_report.md 的 R1。文档里写得出类名，就必须答得出它在哪一行。"""
    bad, n_cls, n_src = [], 0, 0
    for name in discover_examples():
        rp = EXAMPLES / "reports" / f"{name}.report.md"
        log = EXAMPLES / "logs" / f"{name}.log"
        if not rp.exists() or not log.exists():
            continue
        text = read(rp)
        corpus = read(log) + "\n" + read(EXAMPLES / "parsed" / f"{name}.json")
        for fq in sorted(set(FQCN_RE.findall(text))):
            n_cls += 1
            if fq not in corpus:
                bad.append(f"{name}: 类名 {fq} 在日志与 JSON 中均无出处")
        for cls, num in sorted(set(SRC_REF_RE.findall(text))):
            n_src += 1
            if f"{cls}:{num}" not in corpus:
                bad.append(f"{name}: 源码位置 {cls}:{num} 在日志中无对应帧")
    check(not bad, f"报告里 {n_cls} 个类名、{n_src} 处源码位置均可在日志/JSON 回溯",
          "\n".join(bad))


def check_diagnosis_gate():
    """成品报告必须能通过交付给用户的硬校验脚本（子进程跑，看真实退出码）。

    这一项与 check_report_facts 不是重复关系：前者只查"字符串在不在",
    后者还要查证据引用逐字一致、L 号是否落空、异常名是否只出现在否定语境里。
    以子进程方式调用，避免"文档里的命令"和"实际能跑的命令"脱节。
    """
    gate = ROOT / "scripts" / "validate_diagnosis.py"
    if not check(gate.exists(), "交付级硬校验脚本存在（scripts/validate_diagnosis.py）"):
        return

    pairs = []
    for name in discover_examples():
        log = EXAMPLES / "logs" / f"{name}.log"
        rp = EXAMPLES / "reports" / f"{name}.report.md"
        if log.exists() and rp.exists():
            pairs.append((name, log, rp))
    if not check(len(pairs) >= 6, "待硬校验的成品报告 ≥6", f"仅 {len(pairs)} 份"):
        return

    bad = []
    for name, log, rp in pairs:
        cmd = [sys.executable, str(gate), "--log", str(log), "--report", str(rp), "--quiet"]
        parsed = EXAMPLES / "parsed" / f"{name}.json"
        if parsed.exists():
            cmd += ["--parsed", str(parsed)]
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        if proc.returncode != 0:
            detail = proc.stdout.decode("utf-8", "replace").strip().splitlines()
            tail = " ".join(line.strip() for line in detail[:4])
            bad.append(f"{name}: exit={proc.returncode} {tail}")
    check(not bad, f"{len(pairs)} 份成品报告通过 validate_diagnosis 硬校验", "\n".join(bad))


# --------------------------------------------------------------------------
# C4. R2 绝对化措辞：报告与 Step 3 输出不得出现超出证据强度的断言
# --------------------------------------------------------------------------
# 例外：同行带 [事实] 且挂了 E/L 编号，视为已有出处（是否有出处由 R1 检查负责）
ABSOLUTE_RE = re.compile(
    r"(?<![不未非])(肯定是|绝对是|一定是|必然是|必定是|势必|毫无疑问|毋庸置疑|"
    r"唯一原因|根本原因就是|可以断定|不难看出|100%\s*是)"
)


def check_absolute_wording():
    """只扫报告与 Step 3 输出；reviews/ 下的样例会故意引用违规句，故豁免。"""
    bad, total = [], 0
    targets = list((EXAMPLES / "reports").glob("*.report.md")) + \
        [p for p in EXAMPLES.glob("*.md")]
    for md in targets:
        for lineno, line in enumerate(read(md).splitlines(), 1):
            m = ABSOLUTE_RE.search(line)
            if not m:
                continue
            total += 1
            if "[事实]" in line and re.search(r"(E\d|L\d)", line):
                continue  # 有事实标注 + 出处，允许强断言
            bad.append(f"{md.relative_to(ROOT)}:{lineno} 出现“{m.group(1)}”且无 [事实]+出处")
    check(not bad, f"报告与 Step 3 输出无绝对化断言（命中 {total} 处，均带 [事实] 出处）",
          "\n".join(bad))


# --------------------------------------------------------------------------
# C5. 审查样例：判定行与 REVIEW 行必须一致，FAIL 必须给出可定位的打回项
# --------------------------------------------------------------------------
VERDICT_PASS = "【审查通过】"
VERDICT_FAIL = "【审查失败及修改意见】"


def check_review_examples():
    bad, n_pass, n_fail = [], 0, 0
    reviews = sorted((EXAMPLES / REVIEW_DIR).glob("*.review.md"))
    if not check(len(reviews) >= 2, "审查样例 ≥2（通过 + 打回各一）", f"仅 {len(reviews)} 个"):
        return
    for rv in reviews:
        text = read(rv)
        has_pass, has_fail = VERDICT_PASS in text, VERDICT_FAIL in text
        machine_pass = bool(re.search(r"^REVIEW: PASS$", text, re.M))
        machine_fail = bool(re.search(r"^REVIEW: FAIL$", text, re.M))
        if has_pass == has_fail:
            bad.append(f"{rv.name}: 判定行必须且只能有一个（通过 / 失败）")
            continue
        if has_pass and not machine_pass:
            bad.append(f"{rv.name}: 写着【审查通过】却缺 REVIEW: PASS")
        if has_fail and not machine_fail:
            bad.append(f"{rv.name}: 写着【审查失败及修改意见】却缺 REVIEW: FAIL")
        if has_pass:
            n_pass += 1
            if "核查统计" not in text:
                bad.append(f"{rv.name}: 通过样例必须给核查统计（证明查过，而非放水）")
        else:
            n_fail += 1
            rows = [l for l in text.splitlines() if re.match(r"^\|\s*\d+\s*\|", l.strip())]
            typed = [l for l in rows if re.search(r"\|\s*R[1-6]\b", l)]
            if not typed:
                bad.append(f"{rv.name}: 打回表缺 R1–R6 类型标注")
            if "修改意见" not in text:
                bad.append(f"{rv.name}: 打回缺“修改意见”列")
            if "重写要求" not in text:
                bad.append(f"{rv.name}: 打回缺“重写要求”")
    check(not bad, f"审查样例判定自洽（{n_pass} 通过 / {n_fail} 打回，格式可机械校验）",
          "\n".join(bad))


def check_review_index():
    index = read(EXAMPLES / "README.md")
    reviews = sorted((EXAMPLES / REVIEW_DIR).glob("*.review.md"))
    missing = [rv.name for rv in reviews if rv.name not in index]
    check(not missing, f"examples/README.md 收录 {len(reviews)} 份审查样例", f"未提及 {missing}")


# --------------------------------------------------------------------------
# D 安全：危险命令 / TODO / 索引一致
# --------------------------------------------------------------------------
DANGEROUS = (
    (r"kill\s+-9", "kill -9"),
    (r"\brm\s+-r", "rm -r"),
    (r"DROP\s+(TABLE|DATABASE)", "DROP"),
    (r"\bTRUNCATE\s+TABLE", "TRUNCATE"),
    (r"jmap\s+-dump", "jmap -dump"),
    (r"jstack\s+-F", "jstack -F"),
    (r"\breboot\b", "reboot"),
    (r"\bshutdown\s+-", "shutdown"),
)
NEGATIONS = ("禁止", "不得", "不要", "仅限", "只允许", "白名单", "风险", "需在", "变更",
             "避免", "不能", "严禁", "文字建议", "之外", "除外")
# 卸载技能自身安装目录是合法操作，与"排查时删日志/删数据"性质不同，单独放行
SELF_UNINSTALL_RE = re.compile(r"(~|\$HOME)/\.(claude|workbuddy|codebuddy|codex|config)/skills/")


def iter_executable_lines(md: Path):
    """只产出"会被复制执行"的位置：围栏代码块 + 表格行。

    行内代码与普通段落常用来列举禁止项（"不要用 `kill -9`"），把那些也算作违规
    会让文档不敢写禁止清单，反而更危险。
    """
    in_fence = False
    for lineno, line in enumerate(read(md).splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            yield lineno, line
        elif line.lstrip().startswith("|"):
            yield lineno, line


def check_dangerous_commands():
    bad = []
    for md in iter_md():
        if md.name == "safe-commands.md":
            continue  # 该文件本身就是禁止清单，允许出现命令原文
        for lineno, line in iter_executable_lines(md):
            for pattern, label in DANGEROUS:
                if not re.search(pattern, line):
                    continue
                if any(neg in line for neg in NEGATIONS):
                    continue
                if label.startswith("rm") and SELF_UNINSTALL_RE.search(line):
                    continue  # 卸载技能自身安装目录
                bad.append(f"{md.relative_to(ROOT)}:{lineno} 命令表/代码块中出现 {label}")
    check(not bad, "危险命令未出现在代码块或命令表中", "\n".join(bad))


def check_placeholders():
    bad = []
    for md in iter_md():
        for token in ("TODO", "FIXME"):
            if token in read(md):
                bad.append(f"{md.relative_to(ROOT)}: {token}")
    check(not bad, "无 TODO/FIXME 残留", f"{bad}")


def check_examples_index():
    names = set(discover_examples())
    text = read(EXAMPLES / "README.md")
    listed = set(re.findall(r"\(([\w-]+)\.md\)", text))
    listed = {n for n in listed if n not in ("README",)}
    missing = names - listed
    extra = listed - names
    check(not missing and not extra, f"examples/README.md 索引与 {len(names)} 个示例一致",
          f"未列出 {sorted(missing)}；多余 {sorted(extra)}")


# --------------------------------------------------------------------------
def main(argv=None):
    global verbose
    ap = argparse.ArgumentParser(description="严格校验 java-log-diagnoser")
    ap.add_argument("--quiet", action="store_true", help="只输出失败项")
    ap.add_argument("--verbose", action="store_true", help="输出差异细节")
    args = ap.parse_args(argv)
    verbose = args.verbose

    print(f"校验 {SKILL_NAME} @ {ROOT}\n")

    # 先跑脚本，后续多项检查复用同一份真实输出
    live = {}
    try:
        for name in discover_examples():
            live[name] = run_parser(EXAMPLES / "logs" / f"{name}.log")
    except Exception as exc:  # noqa: BLE001
        check(False, "示例日志可被脚本解析", str(exc))

    try:
        check_frontmatter()
        check_files()
        check_referenced_paths()
        check_anchors()

        check_example_sets()
        if live:
            check_schema_version(live)
            check_snapshots(live)
            check_root_line_truth(live)
            check_signal_self_consistency(live)
        check_line_refs()

        check_reports()
        check_red_lines()
        check_workflow_gate()
        if live:
            check_field_names(live)
        check_prompts()
        check_prompt_gates()
        check_evidence_closure()
        check_report_evidence_ids()
        check_report_facts()
        check_diagnosis_gate()
        check_absolute_wording()
        check_review_examples()
        check_review_index()

        check_dangerous_commands()
        check_placeholders()
        check_examples_index()
    except Exception as exc:  # noqa: BLE001  单项崩溃不应吞掉其它结论
        check(False, "校验过程未抛异常", f"{type(exc).__name__}: {exc}")

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
