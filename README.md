# 鸿蒙 DSH 手机试用

独立的 DevEco HarmonyOS Phone 试验工程。官方 DeepSeek Harness 固定为 0.2.2-rc.1。说明和每版结果见 [版本记录](docs/releases.md)。

## 本地构建和版本记录

用 DevEco Studio SDK 26。参考 `build-profile.example.json5` 设置本机 `build-profile.json5`。后者只保留在本机。内置运行时和生产依赖归档也在本地准备，路径及校验值见 `docs/build-inputs.sha256`。现有制品在 `releases/`，构建与安装证据在 `.build/`。

每次变更版本更新 `docs/releases.md`，保留 HAP SHA-256、适用的设备与实测范围。源码提交完成后为已验证版本创建本地 Git 标签。证据中的会话只使用测试数据摘要。
