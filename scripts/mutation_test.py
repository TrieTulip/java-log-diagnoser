#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mutation_test.py —— 验证校验器真的能抓错，而不是只会打印 OK。

做法：把仓库复制到临时目录，注入一类缺陷，再跑校验器，断言
  1) 退出码为 1（确实失败）；
  2) 输出里出现**预期的那条**失败信息（确实是因为这个原因失败，而不是别的检查顺带红了）。

两类目标：
  skill      —— scripts/validate_skill.py 的仓库自检（结构、快照、示例一致性）
  diagnosis  —— scripts/validate_diagnosis.py 的报告硬校验（幽灵行号/异常/类名/引用）
报告侧变异必须单独测：自检再严，也不等于交付给用户的那个脚本能拦住幻觉。

只做只读检查，唯一的写操作发生在临时目录，跑完即删。

用法：
    python3 scripts/mutation_test.py            # 全部跑一遍
    python3 scripts/mutation_test.py --keep     # 保留临时目录，便于排查
退出码：0 全部捕获；1 存在漏过
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns(".git", ".workbuddy", "__pycache__", "node_modules")


# --------------------------------------------------------------------------
# 工具函数：所有变异只通过这几个函数改文件，避免"改了但没写进去"
# 注意：Path.write_text(newline=...) 是 3.10+ 才有，统一走 io.open 以兼容 3.9
# --------------------------------------------------------------------------
def write(path: Path, text: str) -> None:
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def sub(path: Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"变异锚点未命中：{path.name} / {old[:40]!r}")
    write(path, text.replace(old, new, count))


def append(path: Path, extra: str) -> None:
    with io.open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(extra)


def edit_line(path: Path, prefix: str, old: str, new: str) -> None:
    """只改以 prefix 开头的那一行，避免同一段文字在多处出现时改错位置。"""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith(prefix) and old in line:
            lines[i] = line.replace(old, new, 1)
            write(path, "".join(lines))
            return
    raise AssertionError(f"未找到以 {prefix!r} 开头且含 {old!r} 的行：{path.name}")


# --------------------------------------------------------------------------
# 变异用例：每条都必须被 validate_skill.py 抓到，且报错原因与预期一致
# --------------------------------------------------------------------------
CASES = []

# 报告侧变异的固定输入：同一份日志 + 同一份成品报告
DIAG_LOG = "examples/logs/npe-in-commit-chain.log"
DIAG_REPORT = "examples/reports/npe-in-commit-chain.report.md"
DIAG_PARSED = "examples/parsed/npe-in-commit-chain.json"


def case(name: str, expect: str, target: str = "skill"):
    def deco(fn):
        CASES.append((name, expect, fn, target))
        return fn
    return deco


@case("手改 parsed 快照", "快照与脚本当前输出逐字段一致")
def m01(r: Path):
    p = r / "examples/parsed/oom-heap-space.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["summary"]["chain_length"] = 4  # 真实为 2
    write(p, json.dumps(data, ensure_ascii=False, indent=2))


@case("报告行号越界 L99", "L<n> 均指向真实的非空行")
def m02(r: Path):
    sub(r / "examples/reports/dependency-conflict.report.md", "L10", "L99")


@case("报告缺根因章节", "份报告结构合规")
def m03(r: Path):
    sub(r / "examples/reports/startup-port-in-use.report.md", "## 3. 根因假设", "## 3. 猜测")


@case("命令表混入 kill -9", "危险命令未出现在代码块或命令表中")
def m04(r: Path):
    append(r / "examples/reports/oom-heap-space.report.md",
           "\n| 目的 | 命令 | 说明 |\n| --- | --- | --- |\n"
           "| 结束进程 | `kill -9 <PID>` | 立即执行 |\n")


@case("引用不存在的 JSON 字段", "处 JSON 字段名均真实存在")
def m05(r: Path):
    append(r / "examples/npe-in-commit-chain.md", "\n脚本的 `summary.not_a_real_field` 字段。\n")


@case("示例缺成品报告", "均为四件套")
def m06(r: Path):
    (r / "examples/reports/insufficient-info.report.md").unlink()


@case("篡改证据引用一个字", "的引用与 L")
def m07(r: Path):
    # 只改 E3 那一行；"链定位"里也有一模一样的文字，直接 sub 会改错位置
    edit_line(r / "examples/npe-in-commit-chain.md", "E3 | L21 |", "index 1", "index 3")


@case("假设引用不存在的 E9", "引用了不存在的 E")
def m08(r: Path):
    p = r / "examples/npe-in-commit-chain.md"
    text = p.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("- 引用:"):
            sub(p, line, line + ", E9")
            return
    raise AssertionError("未找到 - 引用: 行")


@case("删掉自我审查表", "自我审查表少于 6 行")
def m09(r: Path):
    p = r / "examples/dependency-conflict.md"
    text = p.read_text(encoding="utf-8")
    start = text.index("### 8. 自我审查")
    end = text.index("SELF_CHECK:", start)
    write(p, text[:start] + "### 8. 自我审查\n\nSELF_CHECK: PASS\n" + text[end:])


@case("编造一个不存在的类名", "在日志与 JSON 中均无出处")
def m10(r: Path):
    append(r / "examples/reports/npe-in-commit-chain.report.md",
           "\n另需检查 `com.acme.order.GhostResolver.check()` 的返回值。\n")


@case("报告写绝对化断言", "绝对化断言")
def m11(r: Path):
    append(r / "examples/reports/npe-in-commit-chain.report.md",
           "\n补充：这肯定是缓存击穿导致的。\n")


@case("审查判定与 REVIEW 行不一致", "却缺 REVIEW: PASS")
def m12(r: Path):
    sub(r / "examples/reviews/npe-in-commit-chain.review.md", "REVIEW: PASS", "REVIEW: FAIL")


@case("删掉审查样例", "审查样例 ≥2")
def m13(r: Path):
    (r / "examples/reviews/dependency-conflict.review.md").unlink()


# --------------------------------------------------------------------------
# 报告硬校验（validate_diagnosis.py）：每条都是"模型最可能犯的错"
# --------------------------------------------------------------------------
@case("编造源码行号 :999", "幽灵源码位置", target="diagnosis")
def d01(r: Path):
    sub(r / DIAG_REPORT, "OrderQueryService.java:110", "OrderQueryService.java:999")


@case("断言一个日志没有的异常", "幽灵异常类型", target="diagnosis")
def d02(r: Path):
    append(r / DIAG_REPORT, "\n补充：本次失败由 `GhostCacheException` 触发。\n")


@case("证据引用改一个方法名", "证据引用与日志不一致", target="diagnosis")
def d03(r: Path):
    edit_line(r / DIAG_REPORT, "| E4 | L22 |", "toDetail(", "toDetailX(")


@case("行号写到日志末尾之外", "行号越界", target="diagnosis")
def d04(r: Path):
    append(r / DIAG_REPORT, "\n补充：同类问题另见 L99。\n")


@case("编造一个全限定类名", "幽灵类名", target="diagnosis")
def d05(r: Path):
    append(r / DIAG_REPORT, "\n另需检查 `com.acme.order.ghost.GhostResolver` 的返回值。\n")


@case("删掉 SKILL.md 红线章节", "缺 Zero-Tolerance")
def m19(r: Path):
    p = r / "SKILL.md"
    text = p.read_text(encoding="utf-8")
    start, end = _red_section(text)
    write(p, text[:start] + text[end:])


@case("把红线章节挪到文末", "红线章节必须位于文档开头")
def m20(r: Path):
    p = r / "SKILL.md"
    text = p.read_text(encoding="utf-8")
    start, end = _red_section(text)
    write(p, text[:start] + text[end:] + "\n" + text[start:end])


def _red_section(text: str):
    start = text.find("## 0. 🚫 绝对红线")
    end = text.find("## 1. 何时使用")
    if start == -1 or end == -1 or end < start:
        raise AssertionError("变异锚点未命中：SKILL.md 的红线章节或“何时使用”")
    return start, end


@case("删掉工作流硬校验步骤", "缺 4.2 强制硬校验")
def m21(r: Path):
    sub(r / "SKILL.md", "#### 4.2 强制硬校验（非 0 退出不得交付）", "#### 4.2 人工检查")


@case("改掉 prompts 里的拒诊标记", "未使用 信息不足，拒绝盲目诊断")
def m22(r: Path):
    p = r / "prompts/generate_report.md"
    write(p, p.read_text(encoding="utf-8").replace("信息不足，拒绝盲目诊断", "信息不足"))


@case("报错点退回帧顶（入口认成 DAO）", "快照与脚本当前输出逐字段一致")
def m23(r: Path):
    """把 first_business_frame 改回「帧顶业务帧」。

    栈帧自上而下是被调用者→调用者，取帧顶会把 DAO 当成 HTTP 入口。
    db-connection-timeout 这个示例专门守着这条：改回去快照比对必须红。
    """
    sub(r / "scripts/parse_java_log.py",
        '            for fr in reversed(node["frames"]):\n'
        '                if fr.get("is_business"):\n'
        '                    first_business_frame = fr\n'
        '                    break',
        '            for fr in node["frames"]:\n'
        '                if fr.get("is_business"):\n'
        '                    first_business_frame = fr\n'
        '                    break')


# --------------------------------------------------------------------------
def run_case(name: str, expect: str, mutate, target: str, keep: bool) -> bool:
    tmp_root = Path(tempfile.mkdtemp())
    work = tmp_root / "repo"
    shutil.copytree(ROOT, work, ignore=IGNORE)
    try:
        mutate(work)
        if target == "diagnosis":
            cmd = [
                sys.executable, "scripts/validate_diagnosis.py",
                "--log", DIAG_LOG, "--report", DIAG_REPORT, "--parsed", DIAG_PARSED,
            ]
        else:
            cmd = [sys.executable, "scripts/validate_skill.py", "--quiet"]
        proc = subprocess.run(cmd, cwd=work, capture_output=True,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
        hit = expect in out
        ok = proc.returncode == 1 and hit
        print(f"{'捕获' if ok else '漏过'} | {name:22s} | exit={proc.returncode} | 命中预期：{hit}")
        if not ok:
            detail = out.splitlines()[:4]
            print("\n".join("      " + line for line in detail))
        return ok
    finally:
        if keep:
            print(f"      临时目录保留：{work}")
        else:
            shutil.rmtree(tmp_root, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="对 validate_skill.py 做变异测试")
    ap.add_argument("--keep", action="store_true", help="保留临时目录")
    args = ap.parse_args(argv)

    print(f"变异测试 {len(CASES)} 例 @ {ROOT}\n")
    missed = 0
    for name, expect, mutate, target in CASES:
        if not run_case(name, expect, mutate, target, args.keep):
            missed += 1
    print(f"\n结果：{len(CASES) - missed}/{len(CASES)} 被捕获，{missed} 个漏过")
    return 0 if missed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
