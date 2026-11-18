# 鸿蒙工作区运行时依赖

目标是让官方 `load_workspace_dependencies` 返回鸿蒙应用中的真实 Python、Node 与 pnpm 路径，并使 Office 技能使用与锁定 DSH 相同版本的 Python 库。路径供 Alpine 内的 Bash 使用。依赖查询是只读工具，脚本执行仍由已有 Bash 权限控制。

构建从 PyPI 锁定 CPython 3.12 ARM64 musl wheels 和纯 Python wheels，使用上游的完整版本表。独立应用资源包保存库、发行包元数据和许可证。读取工具沿用 RC.5 的注册、缓存、结果 schema 和卡片。鸿蒙适配提供应用私有布局，安全模式跳过该工具与新增解包。

验收包括覆盖安装前后的官方工具可见性、默认权限下实际查找、一次性批准执行返回路径、代表性的 NumPy、pandas、文档和表格运算、重启复用，以及签名包和启动时长。

0.4.61 通过真实模型查找、Office 技能指引、离线 Python 运算、文档和表格读写、pnpm 执行以及跨重启一致性。独立模拟器清空测试数据到观测 ArkWeb 完成约 48.4 秒，强停重启约 14.3 秒，Python 解包标记复用。 [实测记录](../evidence/emulator-workspace-dependencies-0.4.61.json)
