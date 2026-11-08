# 鸿蒙原型构建与验证

原型使用 DevEco Studio 的 HarmonyOS SDK 26，目标为 ARM64 Phone。构建使用 DevEco 自带的 JDK、Node、ohpm 与 hvigor。当前调试包的 bundle ID 是 `org.sayact.nodepoc`，用于兼容已签名的测试设备和现有测试数据。

## 本地构建

1. 在 DevEco 打开仓库根目录。参考 [build-profile.example.json5](../build-profile.example.json5) 设置本机 `build-profile.json5`。真机需为目标设备配置调试签名。
2. 准备 [构建输入校验表](build-inputs.sha256) 中列出的运行时、原生库和生产依赖归档。仓库记录源码、兼容补丁、打包脚本和校验值。历史 Node 与 DSH 构建还依赖已准备的上游源码树和本地输入，裸检出需要先补齐这些依赖。
3. 在仓库根目录校验输入并运行构建。

```sh
LC_ALL=C shasum -a 256 -c docs/build-inputs.sha256
./build.sh
```

HAP 输出在 `entry/build/default/outputs/default/`。按测试目标记录 signed 或 unsigned 包及 SHA-256。实机使用与现有安装兼容的签名，覆盖安装前核对包名、版本和设备。

## 验证与版本记录

- 用 DevEco 或 HDC 明确选中目标。安装和启动分别检查工具输出和应用实际就绪状态。
- 模拟器启动工具 `scripts/measure-emulator-start.sh <loopback-target> restart` 只接受回环模拟器目标。`fresh` 模式会清空目标应用数据，仅用于可清理的模拟器。
- 用真实任务检查模型、会话恢复、工作区和 Bash 工具。在独立测试工作区检查默认拒绝、单次批准、退出码与取消。测试模型凭据通过受控设置提供，使用后从测试配置移除。
- 版本变更同步写入 [版本记录](releases.md) 和相应证据。证据应包含设备、版本、制品校验值、成功项和失败或未验项。源码提交后为已验证版本保留 Git 标签。

本机签名配置、密钥、构建输入、测试日志和 HAP 按 [Git 忽略规则](../.gitignore) 保存在本机。版本与测试证据使用摘要。
