# OpenHarmony 无障碍库能否随 HAP 实现 Phone Use

2026-11-10。本文的 ACC 指华为 Accessibility Kit 及其对应的 OpenHarmony 无障碍框架。对照 OpenHarmony 6.0 Release 源码、GitHub 默认分支及 DevEco 应用 SDK 26.0.0.105。目标设备是零售版 Mate 60，产品操作由手机端 DSH 发起。 [华为 Accessibility Kit 简介](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/accessibilitykit-overview/) · [OpenHarmony 框架分层](https://github.com/openharmony/accessibility/blob/3ffbe3513f07cb1df2bd98d74089582dff5eb33a/README_zh.md)

普通 HAP 可以携带 ARM64 原生库，已完成编译和打包。OpenHarmony 的跨应用读树、节点动作和手势依赖系统侧授权。现有普通调试签名在 Mate 60 上只验证了前台截图和指定页面跳转，通用跨应用操控仍需可在 Phone 上使用的系统通道。 [Mate 60 真机证据](../evidence/mate60-phone-use-probe.json)

## Accessibility Kit 和系统库

| 组件 | 提供的能力与边界 |
| --- | --- |
| `@kit.AccessibilityKit` 的应用适配接口 | 华为简介列出的公开能力是查询无障碍状态、设置焦点和发送朗读等无障碍事件。`sendAccessibilityEvent` 把事件交给匹配的辅助扩展。事件类型 `click` 描述交互事件，跨应用执行节点动作使用另一条接口。 [华为 Kit 简介](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/accessibilitykit-overview/) · [事件接口](https://developer.huawei.com/consumer/cn/doc/harmonyos-references/js-apis-accessibility/) |
| `accessibleability`、`accessibilityclient`、`accessibilityconfig` | 这些是系统源码树中的 GN 目标，可在匹配的 OpenHarmony 产品构建中编译。客户端还依赖 IPC、SAMgr、无障碍内部接口等系统组件。系统侧会按调用令牌、已连接扩展和相应能力决定是否放行。比如节点查询检查 `retrieve`，手势注入检查连接及 `gesture`。把客户端二进制装入 HAP 不会授予这些权限。 [客户端 GN](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/interfaces/innerkits/aafwk/BUILD.gn#L52) · [系统能力客户端 GN](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/interfaces/innerkits/asacfwk/BUILD.gn#L50) · [配置客户端 GN](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/interfaces/innerkits/acfwk/BUILD.gn#L49) · [动作校验](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/services/aams/src/accessible_ability_channel.cpp#L445) · [手势校验](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/services/aams/src/accessible_ability_channel.cpp#L720) |
| `AccessibilityExtensionAbility` | 旧公开的 `getWindowRootElement`、`performAction`、`injectGestureSync` 从 API 12 起废弃。OpenHarmony 源码仍保留旧接口实现，零售 Mate 60 上普通签名扩展连接后的运行结果待测。API 20 的 `getRootInActiveWindow`、`executeAction` 是要求 `ohos.permission.ACCESSIBILITY_EXTENSION_ABILITY` 的系统接口。 [华为 API 参考](https://developer.huawei.com/consumer/cn/doc/harmonyos-references/js-apis-inner-application-accessibilityextensioncontext/) · [OpenHarmony 兼容实现](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/interfaces/kits/napi/accessibility_extension_module_loader/src/napi_accessibility_extension_context.cpp#L434) · [系统 API](https://github.com/openharmony/docs/blob/442679e8594d9c9c9b2a4bdc9a25a47f1035d6cb/zh-cn/application-dev/reference/apis-accessibility-kit/js-apis-inner-application-accessibilityExtensionContext-sys.md#L733) |
| 应用 SDK 的原生 API | `OH_Input_InjectTouchEvent` 能被原生库链接。华为的公开文档把有效设备限定为 PC／二合一，并说明授权要求。另一个公开接口 `OH_WindowManager_InjectTouchEvent` 只允许同进程窗口。ArkUI 的无障碍 Provider 则负责向系统提供应用自有组件的语义。 [系统触控](https://developer.huawei.com/consumer/en/doc/harmonyos-references/capi-oh-input-manager-h/) · [窗口触控](https://developer.huawei.com/consumer/en/doc/harmonyos-references/capi-oh-window-h/) · [ArkUI Provider 源码](https://github.com/openharmony/arkui_ace_engine/blob/OpenHarmony-6.0-Release/interfaces/native/native_interface_accessibility.h) |
| `uitest` | 测试工具能截图、读布局、点击、滑动、输字。系统构建依赖内部无障碍库和输入服务。读取布局使用 `AccessibilityUITestAbility`，启用通道时系统会检查身份和 Native Token。可以为开发设备验收提供驱动，零售 HAP 的可用范围以实际授权为准。 [工具命令](https://github.com/openharmony/testfwk_arkxtest/blob/c9a697212be4ade7e268e81cfe0fe6d7dd1cfd0c/uitest/server/server_main.cpp#L55) · [工具依赖](https://github.com/openharmony/testfwk_arkxtest/blob/c9a697212be4ade7e268e81cfe0fe6d7dd1cfd0c/uitest/BUILD.gn#L173) · [测试通道校验](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/services/aams/src/accessible_ability_manager_service.cpp#L1675) |

## 编译和打包实测

- 直接通过 `@kit.AccessibilityKit` 编译 ArkTS 扩展。调用 `getWindowRootElement()` 后接 `performAction('click')`，Hvigor 报告两个接口已废弃并成功生成未签名 HAP。改用 `getRootInActiveWindow()` 和 `executeAction()`，编译报错，公开 SDK 中的 `AccessibilityExtensionContext` 与 `AccessibilityElement` 类型没有这两个方法。两组编译均未在设备上执行。
- 用 DevEco NDK 交叉编译 `libacc_link_probe.so`，显式调用系统触控和同进程窗口触控两个 API。Hvigor 构建成功，解包确认文件在 `libs/arm64-v8a/libacc_link_probe.so`。对解出的 ELF 检查架构为 AArch64，动态依赖为 `libohinput.so`、`libnative_window_manager.so` 和 `libc.so`，两个输入符号均存在。
- 同一应用 SDK 分别传入 `-laccessibilityclient`、`-laccessibleability`、`-laccessibilityconfig`，链接器均返回 `unable to find library`。此结果覆盖应用 SDK 的可链接性。系统库的完整产品构建与跨系统二进制兼容性未实测。
- HAP 为未签名的编译探针，两个 C++ 函数未挂到 UI，也未在 Mate 60 安装或调用。本次 HDC 无已连接目标。此前 Mate 60 上返回 `801` 的是 ArkTS `createTouchController()`，应与本次 C++ 构建结果分开看。 [ArkTS 设备约束](https://developer.huawei.com/consumer/en/doc/harmonyos-references/js-apis-inputeventclient/) · [真机证据](../evidence/mate60-phone-use-probe.json)

可在独立工作树的仓库根目录复现。示例复用现有测试 HAP，并在它的暂存工程中加入库。

```sh
deveco=${DEVECO_HOME:-/Applications/DevEco-Studio.app/Contents}
ndk="$deveco/sdk/default/openharmony/native"
stage=.build/stage/harmonyos-phone-use-probe
lib_dir="$stage/entry/libs/arm64-v8a"
mkdir -p "$lib_dir"
cat > "$stage/acc_link_probe.cpp" <<'CPP'
#include <multimodalinput/oh_input_manager.h>
#include <window_manager/oh_window.h>

int ProbeSystemTouch(const struct Input_TouchEvent *event)
{
    return OH_Input_InjectTouchEvent(event);
}

int ProbeWindowTouch(int windowId, struct Input_TouchEvent *event, int x, int y)
{
    return OH_WindowManager_InjectTouchEvent(windowId, event, x, y);
}
CPP
"$ndk/llvm/bin/clang++" --target=aarch64-linux-ohos --sysroot="$ndk/sysroot" \
  -fPIC -shared -nostdlib++ -Wl,--no-undefined "$stage/acc_link_probe.cpp" \
  -lohinput -lnative_window_manager -o "$lib_dir/libacc_link_probe.so"
tests/probes/harmonyos-phone-use/build.sh
hap="$stage/entry/build/default/outputs/default/entry-default-unsigned.hap"
unzip -p "$hap" libs/arm64-v8a/libacc_link_probe.so > "$stage/packaged.so"
"$ndk/llvm/bin/llvm-readelf" -h -d -Ws "$stage/packaged.so"
```

## Mobile Harness 接入

沿用 dsh-Go 的分层。DSH 通过本机工具桥调用手机原生执行器。执行器按机型和已获授权上报 `observe`、`tap`、`swipe`、`type` 的可用范围，动作绑定当前观察并执行后回读。普通鸿蒙包可先暴露已实测的前台截图和指定页面跳转。 [现有架构与 DSH 契约](harmonyos-phone-use.md#对照-dsh-go)

Mate 60 普通签名探针当前只确认扩展可枚举且 `enabled=false`。验证旧接口时，先在系统设置确认用户能否手动启用该独立扩展，再确认连接回调，最后对自建的另一测试 App 读取根节点、点击可逆控件并回读状态。手势与节点动作分别验收。新版系统接口以华为开放的机型、签名和业务授权为准。自有 OpenHarmony 镜像可在匹配的系统源码中构建执行服务，按产品配置授予所需权限，之后接入同一个 DSH 工具桥。产品闭环由 DSH 发起，HDC 用于部署和诊断。 [Mate 60 真机证据](../evidence/mate60-phone-use-probe.json) · [华为 GUI 生态合作](https://developer.huawei.com/consumer/cn/doc/service/agent-gui-0000002680521240/) · [受限权限目录](https://developer.huawei.com/consumer/cn/doc/HarmonyOS-Guides/restricted-permissions/)
