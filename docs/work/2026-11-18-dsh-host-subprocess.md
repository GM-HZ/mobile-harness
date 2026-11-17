# Host 子进程与工作树

目标：补齐 RC.4 公共 subprocess 服务到 Alpine 执行域的桥接，先验证官方 create_worktree；同一基础供后续真实 LSP 使用。保持上游工具、权限、输出限额和生命周期，不另写 Git 工作树工具。

基线：`9cef2f102882102e6e60433a990f77540b93c609`，`codex/harmonyos-package-management`，工作区干净；模拟器普通 0.4.33。DSH 固定 RC.4。只操作 Mobile Harness，用户提供的 SayAct 约定不构成修改另一个产品的授权。

非目标：系统 PTY、Phone Use、真实内核沙箱；不自动把用户会话改成完整权限，不在电脑上代执行 Git 或语言服务器，不修改上游核心。

方案待实测：用 SubprocessRuntime 的可替换 provider 扩展点，复用 LocalSubprocessRuntime 已公开的 spawn hook 和收集／回收实现。探测 Host 原生路径与 Guest 路径是否一致；有真实失败才增加受控路径映射，保留既有 Bash／MCP 契约。公开 hook 是固定版本的适配接口，不宣称跨任意 DSH 版本稳定。

验收：先复现缺工具，再验证真实 Git 初始化、工作树 branch／HEAD／文件、工作目录与会话重启。默认工作区策略在无内核沙箱时仍拒绝；独立完整权限测试会话才能创建。补充流式 stdin/stdout、字面 argv、环境脱敏、退出码、取消／销毁回收。记录原始失败、精确测试源码与 HAP 摘要；恢复临时 profile／锁文件、清理凭据与自建目录。必要回归通过再提交、推送。

状态：调查与复现中。LSP 将在公共执行路径通过后另行装配与验收，当前不声称已支持。
