# OpenHarmony 无障碍库能否随 HAP 实现 Phone Use

2026-11-10。对照 OpenHarmony 6.0 Release 源码和 DevEco 应用 SDK 26.0.0.105。目标设备是零售版 Mate 60，产品操作由手机端 DSH 发起。

普通 HAP 可以携带 ARM64 原生库，已完成编译和打包。OpenHarmony 的跨应用读树、节点动作和手势依赖系统侧授权。现有普通调试签名在 Mate 60 上只验证了前台截图和指定页面跳转，通用跨应用操控仍需可在 Phone 上使用的系统通道。 [Mate 60 真机证据](../evidence/mate60-phone-use-probe.json)

## 命令、系统库与应用 API

| 组件 | 提供的能力与边界 |
| --- | --- |
| `accessibility` 管理命令 | OpenHarmony 的旧命令源码定义了列出、启用、停用扩展和修改无障碍设置，没有读树或坐标点击子命令。6.0 Release 的 `aa` 构建目标未启用旧的 `A11Y_ENABLE` 分支，实际镜像中的命令和入口取决于产品配置。服务端 `EnableAbility`／`DisableAbility` 会检查调用方身份与 `ohos.permission.WRITE_ACCESSIBILITY_CONFIG`。 [命令源码](https://github.com/openharmony/ability_ability_runtime/blob/cd6063a90b273f4364a97ade0e306596e7d2042b/tools/aa/src/accessibility_ability_command.cpp#L121) · [构建和入口](https://github.com/openharmony/ability_ability_runtime/blob/cd6063a90b273f4364a97ade0e306596e7d2042b/tools/aa/BUILD.gn#L89) · [入口源码](https://github.com/openharmony/ability_ability_runtime/blob/cd6063a90b273f4364a97ade0e306596e7d2042b/tools/aa/src/main.cpp#L50) · [服务端校验](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/services/aams/src/accessible_ability_manager_service.cpp#L1398) |
| `accessibleability`、`accessibilityclient`、`accessibilityconfig` | 这些是系统源码树中的 GN 目标，可在匹配的 OpenHarmony 产品构建中编译。客户端还依赖 IPC、SAMgr、无障碍内部接口等系统组件。系统侧会按调用令牌、已连接扩展和相应能力决定是否放行。比如节点查询检查 `retrieve`，手势注入检查连接及 `gesture`。把客户端二进制装入 HAP 不会授予这些权限。 [客户端 GN](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/interfaces/innerkits/aafwk/BUILD.gn#L52) · [系统能力客户端 GN](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/interfaces/innerkits/asacfwk/BUILD.gn#L50) · [配置客户端 GN](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/interfaces/innerkits/acfwk/BUILD.gn#L49) · [动作校验](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/services/aams/src/accessible_ability_channel.cpp#L445) · [手势校验](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/services/aams/src/accessible_ability_channel.cpp#L720) |
| `AccessibilityExtensionAbility` | 旧公开的 `getWindowRootElement`、`performAction`、`injectGestureSync` 在文档中从 API 12 起标为废弃，系统不再向应用开放相应能力。API 20 的 `getRootInActiveWindow`、`executeAction` 是要求 `ohos.permission.ACCESSIBILITY_EXTENSION_ABILITY` 的系统接口。Mate 60 普通签名 HAP 已能枚举扩展，但当时状态为 `enabled=false`，声明的 `retrieve,gesture` 只证明配置被识别。 [公开 API](https://github.com/openharmony/docs/blob/442679e8594d9c9c9b2a4bdc9a25a47f1035d6cb/zh-cn/application-dev/reference/apis-accessibility-kit/js-apis-inner-application-accessibilityExtensionContext.md#L386) · [系统 API](https://github.com/openharmony/docs/blob/442679e8594d9c9c9b2a4bdc9a25a47f1035d6cb/zh-cn/application-dev/reference/apis-accessibility-kit/js-apis-inner-application-accessibilityExtensionContext-sys.md#L733) |
| 应用 SDK 的原生 API | `OH_Input_InjectTouchEvent` 能被原生库链接。华为的公开文档把有效设备限定为 PC／二合一，并说明授权要求。另一个公开接口 `OH_WindowManager_InjectTouchEvent` 只允许同进程窗口。ArkUI 的无障碍 Provider 则负责向系统提供应用自有组件的语义。 [系统触控](https://developer.huawei.com/consumer/en/doc/harmonyos-references/capi-oh-input-manager-h/) · [窗口触控](https://developer.huawei.com/consumer/en/doc/harmonyos-references/capi-oh-window-h/) · [ArkUI Provider 源码](https://github.com/openharmony/arkui_ace_engine/blob/OpenHarmony-6.0-Release/interfaces/native/native_interface_accessibility.h) |
| `uitest` | 测试工具能截图、读布局、点击、滑动、输字。系统构建依赖内部无障碍库和输入服务。读取布局使用 `AccessibilityUITestAbility`，启用通道时系统会检查身份和 Native Token。可以为开发设备验收提供驱动，零售 HAP 的可用范围以实际授权为准。 [工具命令](https://github.com/openharmony/testfwk_arkxtest/blob/c9a697212be4ade7e268e81cfe0fe6d7dd1cfd0c/uitest/server/server_main.cpp#L55) · [工具依赖](https://github.com/openharmony/testfwk_arkxtest/blob/c9a697212be4ade7e268e81cfe0fe6d7dd1cfd0c/uitest/BUILD.gn#L173) · [测试通道校验](https://github.com/openharmony/accessibility/blob/10432e84b77967203337e43d7b4d84a449903d86/services/aams/src/accessible_ability_manager_service.cpp#L1675) |

## 编译和打包实测

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

跨应用操作有两条独立的系统路径。零售 Mate 60 以华为伙伴 GUI 能力的机型、签名和业务授权为准。自有 OpenHarmony 镜像可在匹配的系统源码中构建执行服务，按产品配置授予所需权限，之后接入同一个 DSH 工具桥。两条路径都以 DSH 在真机完成「观察测试 App、点击可逆控件、回读状态」为验收。HDC 用于部署和诊断。 [华为 GUI 生态合作](https://developer.huawei.com/consumer/cn/doc/service/agent-gui-0000002680521240/) · [受限权限目录](https://developer.huawei.com/consumer/cn/doc/HarmonyOS-Guides/restricted-permissions/)
