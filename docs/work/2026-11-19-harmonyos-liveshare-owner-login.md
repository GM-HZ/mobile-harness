# 鸿蒙 LiveShare 所有者授权

DSH RC.5 的分享弹窗在用户点击登录后打开独立窗口，再导航到当前 Relay 的所有者授权入口。鸿蒙原生窗口已有 DeepSeek 登录导航规则。此轮补齐 LiveShare 的入口、Relay 授权页和回传窗口。

入口校验使用 DSH 的授权路径、应用来源、state、PKCE challenge 和 Host 实例标识。LiveShare 窗口允许使用 HTTPS 的 Relay 和身份提供方跳转。隔离测试 Relay 用回环 HTTP。主 ArkWeb 页面继续限定在应用本地地址，DeepSeek 登录继续走已有流程。授权 code、校验值和凭据仍由官方插件交换和管理。

验收用两个独立进程运行实际 DSH Owner 与临时 Relay。通过真实 ArkWeb 界面点击登录，检查 PKCE、一致的回传窗口和已验证的身份。继续检查重启恢复、独立查看者的真实模型回合、未分享会话拒绝、撤销和 Worker 回收。单独复测 DeepSeek 登录。

0.4.59 的原生窗口阻止了同一授权页，Relay 未收到授权请求。0.4.60 在相同模拟器完成窗口授权、PKCE 交换及身份验证。重启后分享恢复，两条源会话可读，独立查看端完成一次真实 DeepSeek 回合，并通过范围拒绝、撤销、停止和线程回收。公网 Relay 和实际 OAuth 身份提供方待验。 [覆盖安装与实测](../evidence/emulator-liveshare-owner-0.4.60.json)
