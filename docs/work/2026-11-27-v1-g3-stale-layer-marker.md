# v1 G3 self/lab 失败：层解包 marker 失效问题

日期：2026-11-27
分支：`codex/harmonyos-v1-device-startup`

## 现象

self 签名构建的 G3 `exec` 中 copy Node 失败（`COPY_NODE_OK=false`，
`COPY_BUSYBOX_EXIT=0` 而非 127）；G3 `overlay` 中 jq 已运行但
`MH_INSTALL_TOOL /usr/bin/.mh-jq` 标记缺失。库 dlopen、扩展 dlopen 正常。

## 根因

`DshEngine.unpack` 的提取 marker 是**按 archive + identity 累积**的：

```
.validated-unpack-v2-shell-extras-v4.zip-<identity>
```

当设备在同一台机器上安装过多个构建（identity X → Y → 又回到 X）后，
旧 identity 的 marker 仍然存在；切回 X 时直接跳过解压，但磁盘上是 Y 构建
解出的内容。例如 `usr/share/mobile-harness/signed-tools.json` 被留成 `{}`，
导致 `mh-install` 走 legacy 路径，输出 `/usr/lib/mh-tools/jq/tool` 而不是
`/usr/bin/.mh-jq`。

## 修复

- 每个 archive 只保留一个 marker：`.validated-unpack-v2-<archive>`；
- marker 内容保存**当前 identity**；
- 启动时仅当 marker 内容等于当前 identity 才跳过解压，否则重新解压并覆盖 marker；
- G1 `host_regressions` 增加该不变量，防止回退。

## 真机验证（Mate 60，self 签名构建）

- 修复后 `exec` PASS：`COPY_NODE_OK=true`，`COPY_NODE_EXIT=0`，
  `COPY_BUSYBOX_EXIT=127`；
- 修复后 `overlay` PASS：`MH_INSTALL_TOOL /usr/bin/.mh-jq`、`jq-1.8.2`、`1`；
- `verify` PASS。

copy Node 的正常执行还依赖历史上的 `5b88294`：`mh-exec-shim.c` 的 `execve`
对相对路径不再提前返回，而是走 unsigned ELF 检测并重定向到 `mh-exec`。
