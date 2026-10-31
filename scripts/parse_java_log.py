#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parse_java_log.py —— 从 Java 报错日志中抽取结构化诊断事实。

设计原则
--------
1. 只抽取、不推断：输出中每个字段都能在原始日志里找到出处；
   log_line 是原始日志的物理行号（从 1 开始），不做任何修正或"美化"。
2. 纯标准库、只读、无网络请求，可直接在用户机器或跳板机上运行。
3. 输出 schema 固定（SCHEMA_VERSION），供 prompts/ 下的模板按字段引用。

用法
----
    cat app.log | python3 scripts/parse_java_log.py
    python3 scripts/parse_java_log.py --file app.log --pretty
    python3 scripts/parse_java_log.py --file app.log --app-package com.acme --pretty

退出码
------
    0  正常（即使没抽到异常也返回 0，summary/warnings 会给出说明）
    2  参数错误或输入不可读
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"

# --------------------------------------------------------------------------
# 正则定义
# --------------------------------------------------------------------------

# 时间戳（用于区分"日志行"与"堆栈里的普通文本行"）
TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}|\b\d{2}:\d{2}:\d{2}[.,]\d{3}\b")
LEVEL_RE = re.compile(r"\b(ERROR|FATAL|SEVERE|CRITICAL)\b")

# "Caused by: java.lang.IllegalStateException: boom"
CAUSED_BY_RE = re.compile(r"^\s*Caused by:\s*(?P<rest>.+?)\s*$")

# "... 23 more"（JDK 省略帧标记，说明日志不完整）
MORE_RE = re.compile(r"^\s*\.\.\.\s+\d+\s+more\s*$")

# 堆栈帧：at com.acme.order.OrderService.create(OrderService.java:88)
# 兼容 Java 9+ 模块前缀：at java.base/java.lang.Thread.run(Thread.java:833)
FRAME_RE = re.compile(
    r"^\s*at\s+(?:[A-Za-z_$][\w$.]*/)?"
    r"(?P<cls>[A-Za-z_$][\w$.]*)\s*\.\s*(?P<method>[A-Za-z_$<>][\w$<>]*)\s*"
    r"\((?P<loc>[^()]*)\)\s*$"
)

# 异常类型：带包限定名，且以 Exception / Error / Throwable 结尾
EXC_TYPE = r"(?:[A-Za-z_$][\w$]*\.)+[A-Za-z_$][\w$]*(?:Exception|Error|Throwable)"
EXC_HEADER_RE = re.compile(r"^(?P<lead>.*?)(?P<type>" + EXC_TYPE + r")(?:\s*:\s*(?P<msg>.*))?$")

# --------------------------------------------------------------------------
# 业务帧判定：默认排除 JDK / 框架 / 日志 / 驱动包
# --------------------------------------------------------------------------
# 这是启发式规则：用户代码通常位于自有域名包下。判定不准时让用户传
# --app-package com.yourcompany，命中即为业务代码，优先级高于排除表。
DEFAULT_NOISE_PREFIXES = (
    "java.", "javax.", "jakarta.", "jdk.", "sun.", "com.sun.", "jdk.internal.",
    "org.springframework.", "org.apache.", "org.hibernate.", "org.mybatis.",
    "org.slf4j.", "ch.qos.logback.", "org.jboss.", "org.eclipse.", "org.glassfish.",
    "io.netty.", "io.undertow.", "reactor.", "io.micrometer.", "com.zaxxer.",
    "com.fasterxml.", "org.junit.", "org.mockito.", "kotlin.", "scala.",
)

# OOM 的具体类型（JVM 输出的固定短语）
OOM_KINDS = (
    "Java heap space",
    "GC overhead limit exceeded",
    "Metaspace",
    "Compressed class space",
    "PermGen space",
    "Requested array size exceeds VM limit",
    "unable to create new native thread",
    "unable to create native thread",
    "Direct buffer memory",
    "Out of swap space",
    "Map failed",
)

# 日志信号：名字 -> (正则, 排查提示)。只用于提示"该看哪一节知识"，不做结论。
SIGNAL_RULES = (
    ("npe", re.compile(r"NullPointerException|空指针", re.I),
     "空指针：先区分三种情况——对象本身为 null、集合/数组元素为 null、自动拆箱时包装类型为 null，修法不同。"),
    ("connection_refused", re.compile(r"Connection refused|java\.net\.ConnectException", re.I),
     "目标端口没有监听或被拦截：先确认服务是否已启动、端口/主机是否配错、ACL 或安全组是否放行。"),
    ("dns_failure", re.compile(r"java\.net\.UnknownHostException", re.I),
     "域名解析失败：确认 /etc/resolv.conf、DNS 服务、hosts 与容器内的解析配置。"),
    ("timeout", re.compile(r"SocketTimeoutException|Read timed out|connect timed out|TimeoutException", re.I),
     "超时类问题：区分连接超时（网络/端口）与读超时（对端处理慢），两者的排查方向不同。"),
    ("class_missing", re.compile(r"ClassNotFoundException|NoClassDefFoundError", re.I),
     "运行时缺类：依赖未打进制品、被 provided/exclusion 排除，或类加载器隔离导致，见依赖冲突章节。"),
    ("version_conflict", re.compile(
        r"NoSuchMethodError|NoSuchFieldError|AbstractMethodError|IncompatibleClassChangeError|LinkageError", re.I),
     "典型的依赖版本冲突：编译期与运行期类版本不一致，用 mvn dependency:tree 定位重复依赖。"),
    ("spring_context", re.compile(
        r"BeanCreationException|UnsatisfiedDependencyException|NoSuchBeanDefinitionException|"
        r"ApplicationContextException|BeanDefinitionStoreException", re.I),
     "Spring 容器启动失败：外层异常通常只是包装，真正原因在最深一层 Caused by。"),
    ("port_in_use", re.compile(r"Address already in use|java\.net\.BindException", re.I),
     "端口被占用：确认是否有残留进程、是否同机多实例、容器端口映射是否冲突。"),
    ("db_error", re.compile(
        r"SQLException|SQLTransientConnectionException|CannotGetJdbcConnectionException|"
        r"DataAccessException|HikariPool|Deadlock", re.I),
     "数据库或连接池问题：区分连接获取失败、SQL 执行失败、死锁、连接泄漏。"),
    ("disk_full", re.compile(r"No space left on device|Disk quota exceeded", re.I),
     "磁盘写满：日志、dump、临时文件都可能撑爆磁盘。"),
    ("permission_denied", re.compile(r"Permission denied|AccessDeniedException|FileNotFoundException.*Permission", re.I),
     "权限不足：文件属主、SELinux、容器只读挂载都会导致。"),
    ("tls_error", re.compile(r"SSLHandshakeException|PKIX path building failed|CertPathValidatorException", re.I),
     "TLS/证书问题：证书过期、信任链缺失、JDK 版本禁用了旧协议。"),
    ("oom", re.compile(r"OutOfMemoryError", re.I), "内存耗尽：见 java-exceptions.md 的 OOM 章节，先分型再动手。"),
)


# --------------------------------------------------------------------------
# 解析辅助
# --------------------------------------------------------------------------
def parse_exception_header(text: str):
    """解析 'com.foo.BarException: message' -> dict 或 None。"""
    m = EXC_HEADER_RE.match(text.strip())
    if not m:
        return None
    exc_type = m.group("type")
    if not re.search(r"(Exception|Error|Throwable)$", exc_type):
        return None
    return {
        "type": exc_type,
        "message": (m.group("msg") or "").strip(),
        "lead": (m.group("lead") or "").strip(),
    }


def parse_frame(line: str, line_no: int):
    """解析单行堆栈帧。返回 dict；不是帧则返回 None。"""
    m = FRAME_RE.match(line)
    if not m:
        return None
    loc = (m.group("loc") or "").strip()
    file_name, file_line = None, None
    lm = re.match(r"^(?P<file>.+?):(?P<line>\d+)$", loc)
    if lm:
        file_name, file_line = lm.group("file"), int(lm.group("line"))
    elif loc and loc not in ("Native Method", "Unknown Source"):
        file_name = loc  # 有文件名但没有行号（编译时未带调试信息）
    return {
        "raw": line.strip(),
        "class": m.group("cls"),
        "method": m.group("method"),
        "file": file_name,
        "line": file_line,
        "log_line": line_no,
        "is_business": None,  # 后置填充
    }


def is_business_class(cls: str, noise_prefixes, app_packages) -> bool:
    """业务代码判定：显式 app_package 优先；否则按排除表做启发式判断。"""
    if app_packages:
        return any(cls == p or cls.startswith(p + ".") for p in app_packages)
    return not any(cls.startswith(p) for p in noise_prefixes)


def match_oom_kind(message: str):
    """从 OOM 消息中识别 JVM 的具体分型。"""
    for kind in OOM_KINDS:
        if kind.lower() in (message or "").lower():
            return kind
    return None


def scan_signals(all_lines, offset: int, max_hits: int = 3):
    """扫描日志正文中的特征串，返回 [{name, hint, evidence:[{log_line, text}]}]。"""
    hits = {name: [] for name, _, _ in SIGNAL_RULES}
    for i, raw in enumerate(all_lines):
        line = raw.rstrip()
        if not line:
            continue
        for name, pattern, _hint in SIGNAL_RULES:
            if len(hits[name]) >= max_hits:
                continue
            if pattern.search(line):
                hits[name].append({"log_line": offset + i + 1, "text": line.strip()[:300]})
    result = []
    for name, _pattern, hint in SIGNAL_RULES:
        if hits[name]:
            result.append({"name": name, "hint": hint, "evidence": hits[name]})
    return result


# --------------------------------------------------------------------------
# 主解析
# --------------------------------------------------------------------------
def parse_log(text, app_packages=(), extra_noise=(), max_lines=50000,
              max_frames=40, max_error_lines=60):
    all_lines = text.splitlines()
    total_lines = len(all_lines)
    offset = 0
    truncated = False
    if max_lines and total_lines > max_lines:
        # 只扫尾部但保留原始行号：offset 用于还原绝对行号，避免编造行号
        offset = total_lines - max_lines
        all_lines = all_lines[offset:]
        truncated = True

    noise = list(DEFAULT_NOISE_PREFIXES) + [p for p in extra_noise if p]
    app = [p for p in app_packages if p]

    chains = []          # 已完成的链
    nodes = []           # 当前链的节点（顶层异常 + 各级 Caused by）
    current = None       # 当前正在追加堆栈帧的节点
    exceptions = []      # 所有异常头（含链内）
    error_lines = []     # 业务报错行 / 非堆栈的错误输出
    warnings = []
    orphan_frames = 0
    truncated_marker = False

    max_exceptions = 200

    def flush_chain():
        nonlocal nodes, current
        if nodes:
            chains.append({"index": len(chains), "nodes": nodes})
        nodes, current = [], None

    for i, raw in enumerate(all_lines):
        log_line = offset + i + 1
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        # ---------- 1) 堆栈帧 ----------
        frame = parse_frame(line, log_line)
        if frame:
            if current is not None:
                node_frames = current["frames"]
                if len(node_frames) < max_frames:
                    frame["is_business"] = is_business_class(frame["class"], noise, app)
                    node_frames.append(frame)
                elif not current["frames_truncated"]:
                    current["frames_truncated"] = True
            else:
                orphan_frames += 1  # 日志从堆栈中间开始
            continue

        if MORE_RE.match(line):
            truncated_marker = True
            continue

        # ---------- 2) Caused by 层 ----------
        caused = CAUSED_BY_RE.match(line)
        if caused:
            head = parse_exception_header(caused.group("rest"))
            if head:
                node = {
                    "depth": len(nodes),           # 0 = 顶层异常，1..n = 第 n 层 Caused by
                    "type": head["type"],
                    "message": head["message"],
                    "log_line": log_line,
                    "raw": stripped[:600],
                    "frames": [],
                    "frames_truncated": False,
                }
                nodes.append(node)
                current = node
                if len(exceptions) < max_exceptions:
                    exceptions.append({"log_line": log_line, "type": node["type"],
                                       "message": node["message"], "depth": node["depth"],
                                       "is_caused_by": True})
                continue

        # ---------- 3) 顶层异常头 ----------
        header = parse_exception_header(line)
        if header:
            looks_like_log_line = bool(LEVEL_RE.search(header["lead"]) or TS_RE.search(header["lead"]))
            # 顶格且无日志前缀的异常行（如 "java.lang.NullPointerException: null"）
            # 视为新的一条错误；已经进入堆栈后的说明文本不打断当前链
            bare_header = (not header["lead"]) and (not line[:1].isspace())
            if current is None or looks_like_log_line or bare_header:
                flush_chain()
                node = {
                    "depth": 0,
                    "type": header["type"],
                    "message": header["message"],
                    "log_line": log_line,
                    "raw": stripped[:600],
                    "frames": [],
                    "frames_truncated": False,
                }
                nodes = [node]
                current = node
                if len(exceptions) < max_exceptions:
                    exceptions.append({"log_line": log_line, "type": node["type"],
                                       "message": node["message"], "depth": 0,
                                       "is_caused_by": False})
                continue

        # ---------- 4) 业务报错行 ----------
        level_match = LEVEL_RE.search(line)
        if level_match and len(error_lines) < max_error_lines:
            error_lines.append({
                "log_line": log_line,
                "level": level_match.group(1),
                "text": stripped[:500],
            })

    flush_chain()

    # ---------------- 后置：选主链 ----------------
    # 主链 = 节点数最多的那条（信息最全）；并列时取靠后的（通常是最后抛出的错误）
    primary = None
    for chain in chains:
        if primary is None or len(chain["nodes"]) >= len(primary["nodes"]):
            primary = chain

    # ---------------- 后置：业务帧聚合（只针对主链，避免多段日志互相污染） ----------------
    business_frames = []
    if primary:
        for node in primary["nodes"]:
            for fr in node["frames"]:
                fr["chain_index"] = primary["index"]
                fr["depth"] = node["depth"]
                if fr.get("is_business"):
                    business_frames.append(fr)
    business_frames = business_frames[:20]

    first_business_frame = business_frames[0] if business_frames else None
    root_business_frame = None
    if primary:
        for node in reversed(primary["nodes"]):
            for fr in node["frames"]:
                if fr.get("is_business"):
                    root_business_frame = fr
                    break
            if root_business_frame:
                break

    # ---------------- OOM 分型 ----------------
    oom = {"present": False, "type": None, "kind": None, "log_line": None, "evidence": None}
    for chain in chains:
        for node in chain["nodes"]:
            if node["type"].endswith("OutOfMemoryError"):
                oom = {
                    "present": True,
                    "type": node["type"],
                    "kind": match_oom_kind(node["message"]),
                    "log_line": node["log_line"],
                    "evidence": node["raw"][:300],
                }
                break
    if not oom["present"]:
        m = re.search(r"OutOfMemoryError[^\n]{0,40}?:\s*([^\n]{0,200})", text)
        if m:
            oom = {
                "present": True,
                "type": "java.lang.OutOfMemoryError",
                "kind": match_oom_kind(m.group(1)),
                "log_line": None,
                "evidence": m.group(0).strip()[:300],
            }

    # ---------------- 摘要 ----------------
    root_node = primary["nodes"][-1] if primary else None
    summary = {
        "exception_count": len(exceptions),
        "chain_count": len(chains),
        "primary_chain_index": primary["index"] if primary else None,
        "chain_length": len(primary["nodes"]) if primary else 0,
        "has_caused_by": any(len(c["nodes"]) > 1 for c in chains),
        "root_cause_type": root_node["type"] if root_node else None,
        "root_cause_message": root_node["message"] if root_node else None,
        "root_cause_log_line": root_node["log_line"] if root_node else None,
        "has_business_frame": bool(business_frames),
        "oom_kind": oom["kind"],
    }

    # ---------------- 告警 ----------------
    if not chains:
        warnings.append("未在日志中解析到异常堆栈：可能只有一行错误文本，或日志格式非标准。")
    if orphan_frames:
        warnings.append(f"发现 {orphan_frames} 个孤立堆栈帧（日志从堆栈中间开始），推断可能不完整。")
    if truncated_marker:
        warnings.append("日志包含 '... N more' 省略帧，堆栈不完整。")
    if truncated:
        warnings.append(f"日志共 {total_lines} 行，仅分析最后 {max_lines} 行（行号已还原为原始行号）。")
    if chains and not business_frames:
        warnings.append("未识别出业务代码帧：请用 --app-package 指定应用根包名后重跑。")
    if not error_lines and not chains:
        warnings.append("未识别到 ERROR/FATAL 级别的日志行。")

    signals = scan_signals(all_lines, offset)

    return {
        "schema_version": SCHEMA_VERSION,
        "parser": {
            "name": "parse_java_log.py",
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "lines_total": total_lines,
            "lines_scanned": len(all_lines),
            "scan_offset": offset,
            "truncated": truncated,
            "app_packages": app,
        },
        "summary": summary,
        "out_of_memory": oom,
        "chains": chains,
        "exceptions": exceptions,
        "business_frames": business_frames,
        "first_business_frame": first_business_frame,
        "root_business_frame": root_business_frame,
        "error_lines": error_lines,
        "signals": signals,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def read_text(path):
    if path:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return sys.stdin.buffer.read().decode("utf-8", errors="replace")


def build_arg_parser():
    p = argparse.ArgumentParser(
        prog="parse_java_log.py",
        description="从 Java 报错日志中抽取 Caused by 链、OOM 分型与业务堆栈帧，输出 JSON。",
    )
    p.add_argument("--file", "-f", help="日志文件路径；缺省从 stdin 读取")
    p.add_argument("--app-package", action="append", default=[],
                   help="应用根包名，可重复，如 --app-package com.acme")
    p.add_argument("--noise-prefix", action="append", default=[],
                   help="追加要排除的包前缀，可重复，如 --noise-prefix com.google.")
    p.add_argument("--max-lines", type=int, default=50000, help="最多扫描的行数（从尾部开始），默认 50000")
    p.add_argument("--max-frames", type=int, default=40, help="每个异常最多保留的堆栈帧，默认 40")
    p.add_argument("--max-error-lines", type=int, default=60, help="最多保留的业务报错行，默认 60")
    p.add_argument("--pretty", action="store_true",
                   help="缩进输出（默认已缩进，保留该参数以便脚本中显式声明）")
    p.add_argument("--compact", action="store_true", help="输出单行 JSON，便于管道传递")
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    try:
        text = read_text(args.file)
    except OSError as exc:
        print(f"[parse_java_log] 无法读取日志: {exc}", file=sys.stderr)
        return 2

    result = parse_log(
        text,
        app_packages=args.app_package,
        extra_noise=args.noise_prefix,
        max_lines=args.max_lines,
        max_frames=args.max_frames,
        max_error_lines=args.max_error_lines,
    )

    try:  # Windows 控制台默认 cp936，显式切 UTF-8 避免中文写不出去
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    json.dump(result, sys.stdout, ensure_ascii=False,
              indent=None if args.compact else 2, separators=(",", ":") if args.compact else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
