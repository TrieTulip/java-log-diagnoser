# 只读排查命令白名单

> **规则**：诊断报告的"建议执行的排查命令"一节，只允许出现本文件列出的命令。
> 所有命令必须带占位符（`<PID>`、`</path/to/app.log>`、`<HOST>`）并说明取值方式，
> 且必须写明"期望观察"。
>
> **风险分级**
> - **A**：完全只读，无副作用，可随时执行。
> - **B**：只读但可能产生短暂影响（安全点停顿、触发 GC），避开业务高峰。
> - **C**：只读且可能改变磁盘/权限状态（落盘、生成大文件），非必要不给。

## 0. 使用前须知

1. `<PID>` 通过 `jps -l` 或 `pgrep -f <主类名>` 获取，不要凭印象填。
2. 容器内执行需先 `kubectl exec` 进入，或改用 `kubectl` 子命令；进入容器本身是只读操作，但不要在里面写文件。
3. 命令一次给 3–5 条即可。给 10 条命令的报告等于没给。
4. 任何需要改文件、改配置、重启、杀进程的操作，**不属于本白名单**，只能写成建议。

---

## 1. 进程与线程

| 目的 | 命令 | 级别 | 说明 / 期望观察 |
| --- | --- | --- | --- |
| 找 Java 进程 | `jps -l` | A | 输出主类名与 PID，据此填 `<PID>` |
| 看启动命令 | `tr '\0' ' ' < /proc/<PID>/cmdline` | A | 确认 `-Xmx`、profile、`-jar` 路径是否符合预期 |
| 看线程数 | `grep Threads /proc/<PID>/status` | A | 线程数异常增长说明线程泄漏 |
| 抓线程栈 | `jstack <PID> \| head -200` | B | 会进入安全点，**极短**停顿；连续抓 2–3 次（间隔 5 秒）才有判断价值 |
| 查锁与死锁 | `jstack -l <PID> \| grep -A 30 "deadlock"` | B | 命中则直接给出持有/等待关系 |
| 找高 CPU 线程 | `top -Hp <PID>` | A | 记录高占用 TID，用 `printf '%x\n' <TID>` 转十六进制后在 jstack 中检索 |
| 看进程资源 | `ps -o pid,ppid,%cpu,%mem,rss,etime,cmd -p <PID>` | A | `etime` 可判断是否刚重启过 |

## 2. 内存与 GC

| 目的 | 命令 | 级别 | 说明 / 期望观察 |
| --- | --- | --- | --- |
| 看 GC 走势 | `jstat -gcutil <PID> 1000 10` | A | 老年代（O）持续接近 100% 且 FGC 频繁 → 内存问题 |
| 看 GC 原因 | `jstat -gccause <PID> 1000 10` | A | 最后一列给出最近一次 GC 触发原因 |
| 看堆概况 | `jcmd <PID> GC.heap_info` | A | 各区容量与使用量，确认是否与 `-Xmx` 一致 |
| 看 JVM 参数 | `jcmd <PID> VM.flags` | A | 确认 `-XX:MaxRAMPercentage` 等是否生效 |
| 看系统属性 | `jcmd <PID> VM.system_properties \| grep -i <keyword>` | A | 排查配置来源、编码、临时目录 |
| 对象直方图 | `jmap -histo <PID> \| head -30` | B | 看 Top 实例；**不要**加 `:live`（会触发 Full GC） |

## 3. 文件与磁盘

| 目的 | 命令 | 级别 | 说明 / 期望观察 |
| --- | --- | --- | --- |
| 磁盘剩余 | `df -h` | A | 使用率 100% → 日志/临时文件写失败 |
| inode 剩余 | `df -i` | A | 大文件不多但 inode 满，常见于海量小文件 |
| 目录占用 | `du -sh <dir>/* \| sort -h \| tail -10` | A | 定位是哪个目录在膨胀 |
| 大文件 | `find <dir> -type f -size +500M -ls` | A | 找异常大文件（dump、日志） |
| 进程打开的文件 | `lsof -p <PID> \| head -50` | A | 确认日志/配置路径，确认句柄是否泄漏 |
| 句柄上限 | `ulimit -a`、`cat /proc/sys/fs/file-nr` | A | `Too many open files` 时必查 |

## 4. 网络

| 目的 | 命令 | 级别 | 说明 / 期望观察 |
| --- | --- | --- | --- |
| 端口监听 | `ss -lntp \| grep <PORT>` | A | 无输出 → 服务未监听，对应 `Connection refused` |
| 连通性 | `nc -zv <HOST> <PORT>` | A | `succeeded` 说明端口可达；`refused` 说明对端没监听 |
| 域名解析 | `dig <HOST> +short` | A | 与预期 IP 不一致 → DNS 问题 |
| 端口占用者 | `lsof -i :<PORT>` | A | 确认是否被其他进程占用 |

> `curl` 仅在明确只读且幂等的 GET 接口上使用，并注明"可能触发一次业务逻辑"。不确定时不要给。

## 5. 日志检索

| 目的 | 命令 | 级别 | 说明 / 期望观察 |
| --- | --- | --- | --- |
| 看上下文 | `grep -n "<业务主键>" </path/to/app.log> \| tail -50` | A | 用订单号/traceId 拉出完整上下文 |
| 统计频次 | `grep -c "<异常关键字>" </path/to/app.log>` | A | 与失败请求数对比，判断是否仍在发生 |
| 看尾部 | `tail -n 500 </path/to/app.log>` | A | 大文件不要 `cat` |
| 时间窗切片 | `awk '/21:04:0/,/21:06:1/' </path/to/app.log>` | A | 只取故障时段 |
| 压缩日志 | `zcat </path/to/app.log.gz> \| grep -n "<keyword>" \| tail -30` | A | 归档日志检索 |

## 6. 依赖与制品

| 目的 | 命令 | 级别 | 说明 / 期望观察 |
| --- | --- | --- | --- |
| 依赖树 | `mvn dependency:tree -Dincludes=<groupId>:<artifactId>` | A | 需在项目目录、可能需要网络；看是否有重复版本 |
| 被仲裁的版本 | `mvn dependency:tree -Dverbose \| grep -i omitted` | A | 定位被悄悄替换的版本 |
| 制品内容 | `unzip -l app.jar \| grep -i "<artifact>"` | A | 确认**实际打进去的** jar，而不是 pom 里写的 |
| 类是否存在 | `unzip -l app.jar \| grep -i "Xxx.class"` | A | `ClassNotFoundException` 必查 |
| JDK 版本 | `java -version`、`javac -version` | A | 排查 `UnsupportedClassVersionError` |

## 7. 数据库（仅只读 SQL）

| 目的 | 命令 | 级别 | 说明 / 期望观察 |
| --- | --- | --- | --- |
| 活跃连接 | `SHOW PROCESSLIST` / `SELECT * FROM pg_stat_activity` | A | 看长事务、`Sleep` 堆积、锁等待 |
| 引擎状态 | `SHOW ENGINE INNODB STATUS` | A | 死锁段与当前等待 |
| 数据核对 | `SELECT ... WHERE ... LIMIT 20` | A | 只查不写；必须带 `LIMIT` |
| 执行计划 | `EXPLAIN <SELECT ...>` | A | 确认是否走索引 |

> 连接串、账号口令一律占位为 `<HOST>` `<USER>`，并提示通过配置中心或运维代查获取，报告里不出现明文。

## 8. 容器与 Kubernetes

| 目的 | 命令 | 级别 | 说明 / 期望观察 |
| --- | --- | --- | --- |
| 看日志 | `kubectl logs <pod> --tail=500` | A | 崩溃循环加 `--previous` 看上一个容器实例 |
| 看事件 | `kubectl describe pod <pod>` | A | 重点看 `Last State`、`Reason: OOMKilled`、退出码 137 |
| 看配置 | `kubectl get pod <pod> -o yaml` | A | 确认 resources limits、env、探针配置 |
| 看资源 | `kubectl top pod <pod>` | A | 与 limits 对比，判断是否被限流/驱逐 |

---

## 9. 禁止清单（不出现在报告的命令中）

| 禁止操作 | 为什么 | 替代做法 |
| --- | --- | --- |
| `kill -9 <PID>`、`kill <PID>` | 变更操作，直接中断在途请求，可能丢数据 | 建议由值班同学在变更窗口执行，报告只描述影响与风险 |
| `jmap -dump:format=b,file=... <PID>` | 落盘 + 长停顿，大堆可能触发 STW 数十秒并写满磁盘 | 建议在预发/低峰执行，或由 JVM 的 `-XX:+HeapDumpOnOutOfMemoryError` 自动产出 |
| `jstack -F <PID>` | 强制 attach 可能让进程挂起 | 用普通 `jstack`；仍失败则说明进程已无响应，属故障现象本身 |
| `jcmd <PID> VM.native_memory` 以外的写操作 | 部分 jcmd 子命令会改变状态 | 只用 `GC.heap_info`、`VM.flags`、`VM.system_properties` 等只读子命令 |
| `systemctl restart/stop`、`kubectl delete/rollout restart` | 变更操作，中断服务且掩盖根因 | 报告中作为"止血选项"文字描述，标注风险与回滚方式 |
| `rm` / `mv` / `truncate` / `> app.log` | 破坏日志现场，无法复盘 | 用 `du`/`find` 定位，交由运维在变更窗口处理 |
| `DROP` / `TRUNCATE` / `UPDATE` / `DELETE` | 不可逆数据变更 | 只给 `SELECT` 核对；修复脚本另行走审批 |
| `FLUSHALL` / 清缓存 / 改配置热更新 | 可能放大故障（缓存击穿） | 描述为"止血候选"，指出副作用 |
| 压测工具（`ab`、`wrk`、`jmeter`） | 生产压测本身是事故 | 严禁 |

---

## 10. 命令怎么给才算合格

| 不合格 | 问题 | 合格 |
| --- | --- | --- |
| `jstack 12345` | PID 写死，读者无法复用 | `jstack <PID> \| head -200`，并注明 `<PID>` 由 `jps -l` 获取 |
| `重启一下服务` | 变更操作，且不是排查 | 不给；改为"检查端口监听：`ss -lntp \| grep <PORT>`" |
| `看看日志` | 无具体动作 | `grep -n "SO20261031001" </path/to/app.log> \| tail -50` |
| 给 12 条命令 | 读者无法执行 | 保留 3–5 条能直接推进结论的 |
| `mysql -uroot -p123456 -e "..."` | 明文口令进报告 | `mysql -h<HOST> -u<USER> -p -e "SELECT ... LIMIT 20"`，凭据由运维提供 |
