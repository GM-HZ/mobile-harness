# 诊断 Inspector Worker 鸿蒙适配

基线：Mobile Harness 251da6c（已推送），codex/harmonyos-package-management，0.4.36准确HAP，DSH RC.4。本任务不修改SayAct；不重复既有九组，除非生产变化影响它们。

目标：解决已复现的Worker profile-resolution-bootstrap缺少node-addon-require-builtin-openharmony-arm64绑定，并验证真正的官方诊断Worker／CDP、鉴权及销毁后主服务恢复。非目标：系统PTY、Phone Use、无关供应商或把CDP调试入口默认开放。沿用官方可选开关，不把Cordis只读查询当诊断Inspector验收。

计划：首先在真实原生Host与execArgv为空的Worker中探测已经随包的固定libguest_require_builtin.so，核对N-API导出、内部加载及实际Node Inspector能力；不先编译新的Node／原生库。不假设Linux字节能在鸿蒙加载。若可用，优先包级平台桥，保持官方Worker和profile路由；只有实测限制才扩大适配。临时插件要求Key槽为空，原配置按本机原字节恢复；Worker／socket／文件在finally清理。

验收：准确制品、真实Worker和Client、鉴权拒绝与CDP实际结果、取消／关闭／重新启用和恢复，分开记录探测可用与完整通过。保留失败和测试口径变化；生产修改须重建新版本、做必要受影响回归后提交推送。

状态：三轮原生探测已执行，完整探针均失败，不算Inspector功能通过。第一轮确认既有libguest_require_builtin.so依赖Linux libstdc++.so.6，原生Host不能加载。第二轮将独立Worker测试与Host绑定失败分离，Worker响应超时。第三轮保留阶段消息，实际Worker完成启动、Inspector导入、connectToMainThread，并通过Runtime.evaluate返回42；Host／Worker的Linux绑定仍失败。原配置按字节恢复，正常模式就绪。

结论：已有Node确实支持Inspector，无需据此重编译Node；尚需解决官方Worker的profile-resolution-bootstrap绑定，以及之后完整CDP／真实Client／鉴权与生命周期验收。已只读获取官方require-builtin源码HEAD a58d3599a2e551d7d706d1ff796c9fd4bbaff63c，其entry版本0.1.9，与现有npm对应；尚未加入生产submodule或编译，也未扩大上游支持矩阵。下一条行动是验证该小型N-API绑定的鸿蒙构建；不可跳过其符号、指针及机器码探测或伪造成功。

[原生探针准确记录](../evidence/emulator-inspector-preflight-0.4.36.json)；本任务仍在进行。
