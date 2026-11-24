# AppGallery 原生 Host 接入

AppGallery 包随附 `appgallery.patch.yml`。Host 使用这份只读包内构建产物确定运行模式，并在 DSH RC.5 的应用自有 profile API 上加载 `mobile-appgallery` 或 `mobile-appgallery-recovery`。首次启动从 `web` 模板初始化，正常升级保留原 profile 和用户设置。恢复模式跳过用户配置层。

`readProfilePatches` 在 AppGallery 模式忽略 Harness home 级补丁，用户 profile 只允许配置已声明的设置项。允许值为普通数据，包括字符串、数字、布尔值、空值和由这些类型构成的对象及数组。启动叠加层禁用第三方插件、终端、MCP 管理、外部包操作、Workflow 和 Office 转换。

工作区搜索复用上游 `glob` / `grep` 工具。`runRipgrep` 在取得工作目录后将请求交给 `dsh-native-search.cjs` 和 `libdshsearch.so`，验证实际工作目录和目标留在本机工作区，支持取消和输出上限。附件继续使用共享的 `dsh-attachment-local` 接入点，由 `dsh-native-image.cjs` 和 `libdshimage.so` 提供 Image Kit 解码。文件写入使用共享的原子发布适配器。

现有 RC.5 接口支持应用指定 profile 和补丁顺序，未暴露 profile 设置过滤、搜索执行器或图像解码器的注入点。G1 固定 profile 设置和工作目录锚点，G2 在 AppGallery 模拟器上验证实际附件接口、搜索工具和受限 RPC。上游提供对应接口时移除运行时改写。
