# 环境

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

- 方案来源：[鸿蒙原生 DSH PoC 任务书](../harmonyos-native-dsh-poc-plan.md)。
- DevEco Studio 26.0.0；模拟器 Phone HarmonyOS 7.0.0.107、API 26、arm64-v8a。
- 真机 HUAWEI Mate 60，系统标识 OpenHarmony 7.0.0.111、API 26、arm64-v8a。
- DSH 测试目标：官方提交 `fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159`，0.2.2-rc.1，要求 Node `>=24.9.0`。
- 已探路运行时：electerm/ohos-node-shared v24.2.0，SHA-256 `3019bf5f9a279d98a87606fc13c53b0e797b6a50cf174f8a1243d880c71151a1`。不满足目标 DSH 版本，仅用于识别平台问题。
- 签名和可下载二进制保存在本机，不加入版本管理。准确制品与日志见工作记录。
