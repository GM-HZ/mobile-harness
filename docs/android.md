# Mobile Harness Android

Android 端复用 [dsh-Go v1.0.12](https://github.com/ccch1mneyyy/dsh-Go/tree/d5ad25c5bc4c66ecacee76b3c5378db45e1db3fa) 的 Flutter 客户端、Kotlin 运行时管理和 Phone Use 桥接。Mobile Harness 提供独立构建入口，应用包名为 `org.mobileharness.android`。本机 DSH 0.2.2-rc.1 在 Ubuntu 24.04 的 PRoot 环境中运行。DSH 经本机 MCP 桥调用 Android 无障碍服务，执行前台动作并读取结果。

## 本地构建

使用 Python 3.11 或以上版本、Flutter 3.47.7、JDK 17、Android SDK 36 和 NDK 28.2.13676358。Flutter SDK 不在 `PATH` 时，设置 `FLUTTER_ROOT`。当前构建支持 ARM64，最低 SDK 为 26，目标 SDK 为 28。目标 SDK 沿用 dsh-Go 的设定，使 PRoot 能执行应用私有目录里的客体程序。APK 用于侧载安装。

```sh
git submodule update --init vendor/repos/dsh-go
mkdir -p .build/inputs/android
gh release download v1.0.12 --repo ccch1mneyyy/dsh-Go \
  --pattern dsh-go-1.0.12-arm64.apk --dir .build/inputs/android
./build.sh android
```

[输入锁定文件](../runtime/android/release-lock.json) 固定了上游源码和已发布的 ARM64 APK。构建先校验上游 APK，再提取 Linux 根文件系统、许可证和四个 PRoot 库，并与运行时清单核对 SHA-256。Flutter 和 Kotlin 应用代码从固定源码构建，并在构建目录应用 Mobile Harness 的配置。可通过 `ANDROID_RUNTIME_APK` 指向同一份已验证的上游 APK。

`./build.sh android --prepare-only` 将源码和运行时组装到 `.build/stage/android`。调试 APK 位于 `.build/stage/android/app/build/app/outputs/flutter-apk/`。每次调用都会重新组装构建目录。使用 `--release` 时，令 `ANDROID_SIGNING_PROPERTIES` 指向本地 Gradle 签名配置，配置中的 `storeFile` 使用绝对路径。将原始签名材料保存在构建目录之外。

已在 Android 15 模拟器使用同一测试证书从 debug 构建覆盖安装 release 构建。原无障碍授权和 DSH 会话得以保留，手动启动本机引擎后可恢复旧会话。新会话已通过 Phone Use 表单、控件点击和截图坐标滑动测试。 [模拟器实测](evidence/android-phone-use-emulator.json)

签名测试包 `11081847` 包含前台读屏重试和 SSH 首次信任修复。Android 15 模拟器覆盖安装后保留了无障碍授权，同一包通过了 DSH 前台点击、SSH 直连断网恢复和文件导出。该包在受控启动延迟下偶尔返回空控件树。 [签名包验收](evidence/android-phone-use-emulator.json)

签名测试包 `11081916` 加入前台目标应用核对。Android 15 模拟器覆盖安装保留了无障碍授权，并通过受控延迟下的目标控件树和首次截图回归。 [冷启动回归](evidence/android-phone-use-emulator.json)

签名测试包 `11081936` 已在 Android 15 模拟器从空白应用数据完成首次初始化。保存自定义模型后，如果本机引擎原来的默认模型不可用，首次引导会把新模型设为新会话默认值。首条会话已完成 DSH 前台点击、状态回读、报告写入和导出。 [首次安装验收](evidence/android-phone-use-emulator.json)

## Phone Use 验证

使用专用测试设备或模拟器。安装 APK 并完成本机运行时初始化，在 Mobile Harness 中开启手机操控，授予无障碍权限，然后重启本机 DSH 以挂载手机工具。

首次引导可选择 **This phone** 和 **Phone control**，设置 **Ask me at key steps**，再按向导开启通知和无障碍。使用测试模型时，从 **Other providers** 添加 **Anthropic** 兼容渠道，Base URL 填 `http://127.0.0.1:18774`，用 `fixture-local-only` 测试密钥发现并保存模型。先启动本机测试端点，并为测试设备配置下方的回环转发。

APK 声明的安装下限为 Android 8（API 26）。截图和依赖截图的坐标操作需要 Android 11（API 30）或更高版本。Android 11–13 使用无障碍全屏截图，Android 14 起在可定位单个窗口时可直接截取窗口。后台屏需要 Android 14 或更高版本及已就绪的特权通道，旧系统的后台屏请求会返回版本要求并提示改用主屏。 [Android 无障碍 API 文档](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService) · [Android 11 模拟器实测](evidence/android-phone-use-api30.json) · [Android 15 模拟器实测](evidence/android-phone-use-emulator.json)

```sh
tests/probes/android-phone/fixture/build.sh
adb -s <target> install -r .build/android-phone-fixture/phone-fixture.apk
```

在 DSH 会话中让 Agent 打开 **Mobile Harness Phone Fixture**，找到并点击 **Toggle sample**，再读取 **SAMPLE_ON**。检查 `mcp__phone__screen` 和 `mcp__phone__tap` 事件，并在任务结束后独立确认界面状态。还应检查拒绝、停止和撤销无障碍权限后的行为。ADB 可用于安装、配置测试环境和采集诊断。

需要确定性复现时，在开发机运行 `python3 tests/probes/android-phone/model.py`，再用 `adb -s <target> reverse tcp:18774 tcp:18774` 转发端口。在一次性测试配置中，把 DeepSeek API Key 设为 `fixture-local-only`，将下列配置写入 `$DSH_HOME/profiles/web/cordis.patch.yml` 并重启引擎。调试 APK 可通过 `adb -s <target> shell run-as org.mobileharness.android` 访问 `files/runtime/rootfs/root/.dsh`。DSH 将 `DEEPSEEK_BASE_URL` 保留给启动环境，在 `$DSH_HOME/.env` 里设置该变量会导致启动失败。

```yaml
- id: llm-deepseek
  config:
    baseURL: http://127.0.0.1:18774
```

在新 DSH 会话发送 `MH_PHONE_FIXTURE`，出现点击审批时选择 **Allow once**。脚本模型向 DSH 请求工具，收到更新后的界面状态才打印确认。请在任务结束后运行 UI Automator 采集独立证据，避免采集工具临时停用无障碍服务。详见 [Android 15 模拟器实测](evidence/android-phone-use-emulator.json)。

发送 `MH_PHONE_FORM_FIXTURE` 可复现截图、输入和滚动。脚本验证 DSH 在模型请求里引用本地 Files API 收到的 JPEG，写入中英文测试文本，滚动到首屏之外的按钮并保存。首次写入审批时选择 **Allow this app for this task**。会话结束后，用 `adb -s <target> shell run-as org.mobileharness.phonefixture cat shared_prefs/form.xml` 独立核对已保存内容。重复该测试前，可用 `adb -s <target> shell pm clear org.mobileharness.phonefixture` 重置专用测试应用的数据。

坐标测试使用安装了 Pillow 的 Python 虚拟环境启动同一个模型脚本。重置专用测试应用数据后，在新会话发送 `MH_PHONE_COORD_FIXTURE`，对两次坐标请求分别选择 **Allow once**。脚本从实际收到的截图定位色块，确认 DSH 拒绝旧截图编号，然后用新截图触发触摸。任务结束后用 `adb -s <target> shell run-as org.mobileharness.phonefixture cat shared_prefs/gestures.xml` 核对触摸次数为 1。

`mcp__phone__swipe_xy` 接受最新标号截图的 `observation`、起点 `x` 和 `y`、终点 `end_x` 和 `end_y`，以截图像素执行一段前台直线滑动。动作走现有确认策略，执行时复查前台应用和截图对应的窗口。路径须留在应用窗口内，并避开屏幕边缘和敏感区域。键盘显示时请先收起。可用 `MH_PHONE_SWIPE_FIXTURE` 测试，按提示批准两个坐标请求，最后用测试应用的 `shared_prefs/gestures.xml` 核对 `swipe_hits` 为 1。Android 15 模拟器已验证旧截图被拒绝，新截图触发一次滑动，DSH 读回 `SWIPE_HITS_1`。 [模拟器实测](evidence/android-phone-use-emulator.json)

发送 `MH_PHONE_SECURE_FIXTURE` 可检查 Android 安全窗口。对 **Protect fixture window** 的点击选择 **Allow once**。测试应用开启 `FLAG_SECURE` 后，DSH 应对截图请求返回安全窗口错误，且不向模型附加图片。再次运行前重启专用测试应用。

发送 `MH_PHONE_COLD_READ_FIXTURE` 可检查冷启动读屏。先强停专用测试应用，再在新的 DSH 会话发送该标记。脚本要求 `open` 返回测试应用控件树，并要求随后的 `screen` 同时返回控件树和 JPEG。可在测试应用的 `shared_prefs/fixture_config.xml` 中设置 `<map><int name="launch_delay_ms" value="2000" /><string name="image_tag">trial-01</string></map>`。延迟用于拉长启动过渡，画面标记用于区分每轮 JPEG。重复测试时换一个标记，测试后删除该文件。

`open(app)` 发出前台启动请求后，最多再重读三秒以确认目标应用窗口。普通 `screen` 遇到窗口列表为空或前台根节点缺失时，最多重读两秒。仍无可读窗口时，DSH 会省略截图。 [Android 11 模拟器实测](evidence/android-phone-use-api30.json) · [Android 15 模拟器实测](evidence/android-phone-use-emulator.json)

发送 `MH_PHONE_HANDOFF_FIXTURE` 可检查 DSH 将手机交给用户的流程。清空专用测试应用数据后启动任务，选择 **Continue**，再批准 DSH 的点击。确认 DSH 先重新读屏，随后读回 `SAMPLE_ON`。另一条新会话在交还时选择 **Stop task**，应停止该任务且不发起点击。用 UI Automator 采集独立证据时，等任务结束后再启动。 [release 实测](evidence/android-phone-use-emulator.json)

后台屏测试走 **手机操控 → 不打扰模式 → Direct ADB**。在专用测试设备完成无线调试配对和连接后，重置测试应用数据，再从 DSH 会话发送 `MH_PHONE_BACKGROUND_FIXTURE`。DSH 在独立显示屏打开测试应用，读取按钮，获批后点击并读回 `SAMPLE_ON`。可在审批期间用 `adb -s <target> shell dumpsys activity activities` 分别核对主屏与测试应用所在的显示屏，并在任务结束后从测试应用的 `shared_prefs/gestures.xml` 核对 `sample_on`。

后台通道自检由 Mobile Harness 应用进程在一次性虚拟屏上创建接收窗口，由特权进程同步输入事务并注入测试触摸。自检收到匹配的按下和抬起事件，并释放窗口和虚拟屏后才报告就绪。Android 15 模拟器上两次启用均通过，随后同一 release 包完成了 DSH 后台点击和结果回读。 [后台自检补丁](../runtime/android/patches/background-input-probe.patch) · [实测记录](evidence/android-phone-use-emulator.json)

系统明确报告无线调试关闭时，Direct ADB 的建连和后台工具请求会被拒绝，已有通道可用于释放任务资源。Android 15 模拟器已验证，关闭后的新后台任务未启动目标应用，等待审批的后台点击在随后批准时也被拒绝。前台无障碍点击仍可独立运行。

发送 `MH_SHELL_FIXTURE` 可验证命令的实际执行宿主。Android 15 模拟器缺少 DSH 可用的命令沙箱，默认 `workspace-write` 调用被拒绝。脚本对同一条测试命令申请单次扩大权限，批准后检查命令输出。日常会话使用 DSH 的常规权限策略。

## 工作区产物

重置专用测试应用数据后，在本机新会话发送 `MH_PHONE_REPORT_FIXTURE <12 位小写十六进制 ID>`，再批准 DSH 点击 **Toggle sample**。模型读回 `SAMPLE_ON` 后通过 `write` 和 `read` 生成并核对 `mh-phone-report-<ID>.txt`。打开 **会话详情 → 文件** 可预览，也可从预览的 **更多操作** 保存到 Android 下载目录。Android 15 模拟器上的签名 release 已验证强停后重新打开原会话和文件，导出的 UTF-8 内容逐字节一致。 [实测记录](evidence/android-phone-use-emulator.json)

## SSH 宿主

从 **切换主机 → 管理远程主机** 添加已安装 DSH 的 SSH 宿主，核对主机指纹并切换到该宿主。如果 SSH Shell 找到的 DSH 或 Node 版本不兼容，在 **启动命令** 中指定可用的 DSH 启动路径并追加 `web`。Android 15 模拟器已连接运行 DSH 0.2.2-rc.1 的隔离 macOS 宿主，经 SSH 隧道执行测试命令，并在重启客户端后恢复原会话。

签名测试包 `11081936` 也通过虚拟网卡连接了 Ubuntu 24.04.5 ARM64 容器。宿主使用 Node 24.22.1 和 npm 发布版 DSH 0.2.2-rc.1，以非 root 用户运行。手机本机引擎保持停止，SSH 和模型请求分别通过虚拟网卡和容器内回环访问。已验证首次指纹确认、执行中断网恢复原会话、从手机停止宿主任务，以及工作区报告导出。 [Ubuntu 宿主实测](evidence/android-phone-use-emulator.json)

测试未信任的 SSH 宿主时，应用先探测指纹并关闭连接，等待用户核对。用户确认后，应用新建认证连接并校验刚确认的指纹。Android 15 模拟器已验证等待 35 秒后可以完成登录，等待期间宿主换钥会在认证前被拒绝。 [模拟器实测](evidence/android-phone-use-emulator.json)

隔离 SSH 宿主可用 `MH_SSH_RESUME_FIXTURE <12 位小写十六进制 ID>` 复现执行中断线。测试模型让 DSH 在工作区新建 `mh-ssh-resume-<ID>`，写入 `START`，然后等待该目录出现 `release` 文件。观察到 `START` 后中断客户端 SSH 连接，在宿主创建 `release` 并确认 DSH 完成任务，再恢复连接。Android 15 模拟器自动重连并在原会话显示结果。工作区只记录一次 `START` 和 `FINISH`。沙箱可用时，DSH 日志只记录一次工具调用和结果。

Ubuntu 容器上的 DSH 在命令开始前因沙箱不可用而拒绝了默认调用。测试模型只对这类拒绝申请一次执行同一条测试命令的批准。选择 **Allow once** 后再执行断网步骤。该轮日志记录一次拒绝和一次执行，工作区仍各只记录一次 `START` 和 `FINISH`。 [Ubuntu 断网实测](evidence/android-phone-use-emulator.json)

Android 15 也已通过模拟器虚拟网卡直连宿主机 SSH。测试时启用飞行模式并关闭 Wi-Fi，确认 TCP 不可达，再在宿主释放任务。恢复网络后，客户端重新完成 SSH 认证并在原会话显示结果，宿主 DSH 进程持续运行。SSH 端口未配置 `adb reverse`。 [直连断网实测](evidence/android-phone-use-emulator.json)

用新 ID 重跑时，可以在 `START` 后从手机端停止任务。宿主应记录用户取消并终止对应 Bash 作业。随后创建 `release`，工作区应仍只含 `START`。Android 15 模拟器已通过该检查。 [模拟器实测](evidence/android-phone-use-emulator.json)

使用 `MH_SSH_APPROVAL_FIXTURE <12 位小写十六进制 ID>` 检查远端审批。测试模型请求一次 Bash 权限提升。在命令等待审批时断开并恢复 SSH 隧道，从原会话选择 **Allow once**。确认 DSH 日志中的审批请求与决定 ID 一致，作业在批准后才启动，宿主文件 `mh-ssh-approved-<ID>` 只写入一行 `APPROVED`。用新 ID 选择 **Decline** 时，DSH 应记录拒绝，且无作业和文件。Android 15 模拟器通过了两种检查。 [模拟器实测](evidence/android-phone-use-emulator.json)

在 SSH 宿主的新会话发送 `MH_SSH_REPORT_FIXTURE <12 位小写十六进制 ID>`，由宿主 DSH 写入并读回 `mh-ssh-report-<ID>.txt`。在 Android 的 **会话详情 → 文件** 打开报告，从预览保存到下载目录，再与宿主工作区的原文件做字节比对。Android 15 模拟器的签名 release 已通过这条链路。 [实测记录](evidence/android-phone-use-emulator.json)

Android 构建保留 dsh-Go 的作者署名、[AGPL-3.0 许可证](../vendor/repos/dsh-go/LICENSE)和第三方声明。分发时需按适用许可证提供源码和声明。此构建默认关闭匿名使用统计，并停用上游版本更新提示。
