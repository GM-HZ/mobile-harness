# 产品官网维护

官网入口是 `site/index.html`，英文页为 `site/en.html`。两页共用样式和本地图片，不依赖构建工具或外部运行时。内容以[第一可用版本计划](work/2026-11-21-first-usable-version.md)和[能力矩阵](architecture/feature-roadmap.md)为准。更新能力、试用流程或变体限制时同步两种语言。

## 本地预览

在仓库根目录运行：

```sh
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

打开 [中文首页](http://127.0.0.1:8000/) 或 [英文首页](http://127.0.0.1:8000/en.html)。

## GitHub Pages

首次部署时在[仓库 Pages 设置](https://github.com/GM-HZ/mobile-harness/settings/pages)把发布源设为 **GitHub Actions**。合入 `main` 后，`Publish product website` 工作流仅上传 `site/`，也可从 `main` 手动触发。默认官网地址为 [gm-hz.github.io/mobile-harness](https://gm-hz.github.io/mobile-harness/)。

`site/` 是公开发布目录，只存放站点内容。文档与验证证据通过仓库链接访问。图标沿用鸿蒙 App 蓝鲸标识，首页手机图是品牌插图。
