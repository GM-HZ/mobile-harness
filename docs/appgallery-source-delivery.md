# DSH-MH 0.4.27 商店版源码交付

适用于 HarmonyOS 包名 `org.mobileharness.dshmh`、构建号 34。本地已生成源码归档和 SHA-256 校验文件，正式下载位置待确定。归档中的 `package-provenance.json` 记录本地候选安装包、随包 DSH 层和各原生库的摘要。正式签名后应重新生成或核对安装包摘要，并记录签名版本。

| 组件 | 归档内材料 |
| --- | --- |
| DeepSeek Harness 和 dshm | 固定提交的源码归档。对应提交见 `package-provenance.json`。 |
| DSH-MH 鸿蒙集成 | 包含 ArkTS、C、Rust、宿主适配、商店配置和构建脚本的 Git 源码归档。 |
| 鸿蒙 Node.js 24.14.1 | 已核验的上游源码、八份鸿蒙补丁和历史构建脚本。源码准备步骤已验证，完整编译仍需复验。 |
| 原生工作区搜索 | Rust 锁文件、参与 OHOS ARM64 构建的 crate 源码归档、Rust 编译器版本与提交，以及安装包中对应版权说明。 |

精简后的送审候选包已移除 LibreOffice Kit 的 Node 适配器及 WASM 引擎。此前候选包的 LibreOffice Core 源码、补丁和配方留存在本机历史归档。当前包的组件清单以 `package-provenance.json` 为准。

Rust 标准库的提交见 `package-provenance.json`。源码随对应的 Rust 工具链版本公开。 [Rust 固定源码](https://github.com/rust-lang/rust/tree/31fca3adb283cc9dfd56b49cdee9a96eb9c96ffd)

```sh
shasum -a 256 -c dsh-mh-0.4.27-appgallery-source.tar.gz.sha256
tar -xzf dsh-mh-0.4.27-appgallery-source.tar.gz
cd dsh-mh-0.4.27-appgallery-source
shasum -a 256 -c SHA256SUMS
```

商店版的正式源码下载地址通过 `HARMONY_APPGALLERY_SOURCE_URL` 进入应用内开源软件声明。本地归档及其摘要已准备，公开下载位置待确定。
