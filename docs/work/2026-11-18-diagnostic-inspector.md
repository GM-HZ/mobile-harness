# 诊断 Inspector Worker 鸿蒙适配

基线：Mobile Harness 251da6c（已推送），codex/harmonyos-package-management，0.4.36准确HAP，DSH RC.4。本任务不修改SayAct；不重复既有九组，除非生产变化影响它们。

目标：解决已复现的Worker profile-resolution-bootstrap缺少node-addon-require-builtin-openharmony-arm64绑定，并验证真正的官方诊断Worker／CDP、鉴权及销毁后主服务恢复。非目标：系统PTY、Phone Use、无关供应商或把CDP调试入口默认开放。沿用官方可选开关，不把Cordis只读查询当诊断Inspector验收。

计划：首先在真实原生Host与execArgv为空的Worker中探测已经随包的固定libguest_require_builtin.so，核对N-API导出、内部加载及实际Node Inspector能力；不先编译新的Node／原生库。不假设Linux字节能在鸿蒙加载。若可用，优先包级平台桥，保持官方Worker和profile路由；只有实测限制才扩大适配。临时插件要求Key槽为空，原配置按本机原字节恢复；Worker／socket／文件在finally清理。

验收：准确制品、真实Worker和Client、鉴权拒绝与CDP实际结果、取消／关闭／重新启用和恢复，分开记录探测可用与完整通过。保留失败和测试口径变化；生产修改须重建新版本、做必要受影响回归后提交推送。

状态：开始原生绑定与Inspector预探测。
