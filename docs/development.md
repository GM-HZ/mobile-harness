# 鸿蒙构建与验证

使用 DevEco Studio SDK 26 和 ARM64 Phone。构建使用 DevEco 自带的 JDK、Node、ohpm 和 hvigor。普通构建的调试包保持 `org.sayact.nodepoc`，用于兼容已有签名和测试数据。

## 获取源码

```sh
git submodule update --init --depth=1
./scripts/vendor/verify.sh
```

父仓库 Git 链接固定每个组件的完整提交。当前直接子模块为 DSH、Node、Termux PRoot、DSHM 和 Termony。构建只读取锁定的子模块，DSHM 的 fetch shim 与许可证直接取自相应子模块。Termony 的嵌套终端组件在当前路径未使用。升级子模块时先提交并推送上游改动，再更新父仓库的 Git 链接。

## 准备输入并打包

1. 备齐 [输入清单](build-inputs.sha256) 指定的 0.4.24 原始打包输入，保留清单中的相对路径。已有开发机的输入存放在 `.build/inputs/harmonyos/`，也可通过 `HARMONY_INPUTS_DIR` 指向一份外部输入目录。当前配方使用已校验的输入字节，Node、DSH 和 PRoot 的全量源码复建仍需补齐。
2. 参考 [DevEco 配置示例](../apps/harmonyos/build-profile.example.json5) 设置本机签名。签名配置从仓库根目录的 `build-profile.json5` 或 `HARMONY_SIGNING_PROFILE` 读取。模拟器用 `HARMONY_UNSIGNED=1`。
3. 在仓库根目录运行：

```sh
HARMONY_UNSIGNED=1 ./build.sh
```

`./build.sh --prepare-only` 生成 DevEco 暂存工程。编辑源文件用 `apps/harmonyos/`，在 DevEco 打开 `.build/stage/harmonyos/` 进行构建或调试。仓库保留源码、补丁与摘要。运行时输入和签名配置保存在本机。

## 打包与发布

```sh
HARMONY_UNSIGNED=1 ./build.sh --package
HARMONY_SIGNING_PROFILE=/absolute/path/to/build-profile.json5 ./build.sh --package
```

`--package` 在 `.build/artifacts/harmonyos/` 生成带版本的 ARM64 HAP 及各自的 `.sha256` 文件。未签名包供 Phone 模拟器使用。普通调试签名包适用于签名配置覆盖的真机，可以在同包名、同签名且版本号更高时覆盖安装。

GitHub Actions 的 **Build HarmonyOS HAP** 可在 `main` 上手动触发。注册带 `deveco` 标签的 ARM64 macOS runner，并预装 DevEco Studio SDK 26。将校验清单中的运行时输入存放在 runner 检出目录之外。通过仓库 Actions 变量 `DEVECO_HOME` 和 `HARMONY_INPUTS_DIR` 指定绝对路径。工作流调用同一个打包命令并上传未签名 HAP 和校验文件。

在模拟器通过回归后，从对应的 Git 提交创建 Release。发布包名中的版本号来自 `apps/harmonyos/AppScope/app.json5`，例如以下命令上传 0.4.26 的模拟器包。需要分发真机调试包时，将 `signed.hap` 及其校验文件一同附到该私有仓库的 Release。

```sh
version=0.4.26
git push origin main
gh release create "v$version" --target "$(git rev-parse HEAD)" \
  --title "DSH-MH $version · HarmonyOS" --notes-file /absolute/path/to/release-notes.md \
  .build/artifacts/harmonyos/dsh-mh-harmonyos-arm64-v"$version"-unsigned.hap{,.sha256}
```

## AppGallery 候选包

```sh
HARMONY_APPGALLERY_BUNDLE=<开发者中心登记包名> ./build.sh --appgallery
```

此命令在 `.build/stage/harmonyos-appgallery/` 生成独立的 DevEco 工程，在 `.build/artifacts/harmonyos-appgallery/` 输出 Release 模式的未签名 `.app` 和校验文件。用 DevEco Studio 26 打开该暂存工程，通过「构建 → 上传产品」选择对应的 HarmonyOS 应用并使用开发者中心云管理证书签名。随包 HAP 可在 Phone 模拟器验证。 [华为发布说明](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-publish-app/)

应用市场版本在用户同意隐私提示后启动本机 Host。该版本使用独立的 DSH profile，限制外部插件安装、远程接入和通用子进程执行，保留本机工作区、会话及随包搜索能力。提交审核前按实际分发方式核对应用主体、备案及 AI 资质，使用同一个隐私政策版本生成应用内说明和公开链接，并为随包工具补齐对应源码和许可证。

## Phone 模拟器回归

显式选定回环 HDC 目标，安装并启动待测 HAP。故障夹具会在独立 Phone 模拟器上安装一个测试 DSH bundle，主动让 Host 进程崩溃并恢复正常 profile。测试使用模拟器测试数据。

```sh
tests/bench/measure-emulator-start.sh <loopback-target> restart
python3 tests/smoke/emulator-recovery.py <loopback-target> .build/emulator-recovery.json
```

启动计时的 `fresh` 模式会清空目标 App 数据，仅用于独立模拟器。恢复测试要求正常模式已启动，并会记录匿名鉴权、插件崩溃、安全模式和旧会话续接。

## Host 进程探针

```sh
HARMONY_EXPERIMENTAL_HOST_PROCESS=1 ./build.sh
```

此模式在 `.build/stage/harmonyos-process-probe/` 生成独立包 `org.mobileharness.processprobe`。它使用实验性的进程启动方式，适用于 Phone 模拟器实验。原生恢复页在实验包中终止并重新启动 Host，同时 UI 可继续运行。普通构建仍由应用内 Node 启动，恢复页以重新打开应用为恢复边界。使用同一模拟器验证两种包时，应先停止另一包，两个 DSH 实例使用同一个回环端口。
