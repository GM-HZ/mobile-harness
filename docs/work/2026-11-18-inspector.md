# 鸿蒙 Inspector

基线 0.4.42、DSH RC.5、Mobile Harness `d6aa558`。目标是通过官方可选 bundle 在 ArkWeb 启停诊断，验证 Host 与客户端的 CDP 请求。0.4.42 模拟器已复现 Worker 找不到鸿蒙 require-builtin，插件进入 failed，鉴权后的诊断入口返回 404。

官方 Worker 单独启动时未继承 Host 的内部模块选项。沿用 Node 内置模块，在这个 Worker 内映射 profile resolver 所需的五项加载接口。官方同源 DevTools 代理沿用会话鉴权，代理用现有 Worker 内部令牌连接，保留 ArkWeb 的 ingest 协议。直连 Worker 的发现和 CDP 请求需要内部令牌。

验收检查默认关闭、正常启用、鉴权拒绝、正式 DevTools 静态入口、真实 CDP 请求、ArkWeb realm、跨重启启用与关闭后的连接回收。保留旧会话和原配置。外部桌面 Chrome 自动拉起和其他设备诊断独立验收。

0.4.43 的 Worker preload 早于 Node 填充脚本参数，启动报错，原配置恢复。0.4.44 通过 Worker 启动数据传入已锁定的入口，消除这个时序依赖。模拟器的原生快捷键拉起 ArkWeb 底部 DevTools，实际 iframe 可见且加载完成。Host 求值返回 42，真实 ArkWeb Document 的节点类型为 9。匿名代理返回 401，直连 Worker 的发现及 CDP 升级返回 403。关闭后端口释放。

同一制品补验 Cordis、LSP 开关和故障恢复。最终保持默认工作区写权限、原配置与旧会话事件摘要。设备空间不足时仅清理本模拟器中旧 RC.4 的可重建解包层，已校验原 HAP。实机仍待验证。[实测记录](../evidence/emulator-inspector-0.4.44.json)
