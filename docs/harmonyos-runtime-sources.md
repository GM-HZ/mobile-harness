# HarmonyOS 候选包的 Alpine 组件来源

以下对应商店候选包 0.4.26 的输入字节。版本、许可证字段和打包提交来自 Alpine 原始包的 `.PKGINFO` 或官方 minirootfs 的已安装包清单。

- 从 Alpine v3.22 的 aarch64 镜像下载 [guest-tools-lock.json](guest-tools-lock.json) 的 25 个 APK，逐一匹配锁文件 SHA-256。用现有打包脚本重选内容，110 个签名库输入及 655 个数据条目均与候选包暂存输入一致。
- Bash、libstdc++ 与下表 Alpine APK 内成员逐字节相同。Readline、ncurses、libgcc 对照 Alpine APK 时仅多出尾部的零填充，分别为 107824、128128、129136 字节。
- BusyBox 和 musl 解释器与 Alpine 3.22.8 aarch64 官方 minirootfs 中的文件逐字节相同。校验基准见 [build-inputs.sha256](build-inputs.sha256)。

| Alpine 软件包 | 许可证（包元数据） | 对应打包源码 |
| --- | --- | --- |
| `brotli-libs-1.1.1-r0` | MIT | [brotli](https://github.com/alpinelinux/aports/tree/0b8db0af6fbe8b8bc7e50e5f64b2f88bc0d6aa16/main/brotli) |
| `c-ares-1.34.9-r0` | MIT | [c-ares](https://github.com/alpinelinux/aports/tree/2abc7d1defd146f59390a22caf74efe85e5130d9/main/c-ares) |
| `ca-certificates-bundle-20261020-r0` | MPL-2.0 AND MIT | [ca-certificates](https://github.com/alpinelinux/aports/tree/ce7bff87478cd936f5b7031ce822b02d4fdd313a/main/ca-certificates) |
| `gdbm-1.24-r0` | GPL-3.0-or-later | [gdbm](https://github.com/alpinelinux/aports/tree/cf76e1b436494c60e0c188400007dbf78bbff5f0/main/gdbm) |
| `git-2.49.1-r0` | GPL-2.0-only | [git](https://github.com/alpinelinux/aports/tree/d896b70b77339c50bea678a19895df6331872d82/main/git) |
| `git-init-template-2.49.1-r0` | GPL-2.0-only | [git](https://github.com/alpinelinux/aports/tree/d896b70b77339c50bea678a19895df6331872d82/main/git) |
| `libbz2-1.0.8-r6` | bzip2-1.0.6 | [bzip2](https://github.com/alpinelinux/aports/tree/33283848034c9885d984c8e8697c645c57324938/main/bzip2) |
| `libcrypto3-3.5.9-r0` | Apache-2.0 | [openssl](https://github.com/alpinelinux/aports/tree/b6d0d5c5639c0034e9073c39e9ff139e28e71818/main/openssl) |
| `libcurl-8.14.1-r4` | curl | [curl](https://github.com/alpinelinux/aports/tree/d1a2a43ff0517fffb947e767cdaeee61e7376cf2/main/curl) |
| `libexpat-2.10.0-r0` | MIT | [expat](https://github.com/alpinelinux/aports/tree/e7473064be733caf6876525ecc41181e5137f399/main/expat) |
| `libffi-3.4.8-r0` | MIT | [libffi](https://github.com/alpinelinux/aports/tree/be5e49159a2ccca93a3290af3d8ab25443523363/main/libffi) |
| `libidn2-2.3.7-r0` | GPL-2.0-or-later OR LGPL-3.0-or-later | [libidn2](https://github.com/alpinelinux/aports/tree/1cdcdd0eccbee1f60078417a7aaf83f92f6e6754/main/libidn2) |
| `libpanelw-6.5_p20250503-r0` | X11 | [ncurses](https://github.com/alpinelinux/aports/tree/3fefbe8dda8b3e85458edb190e2f3a69ad16035c/main/ncurses) |
| `libpsl-0.21.5-r3` | MIT | [libpsl](https://github.com/alpinelinux/aports/tree/4cf07ce428e77d8bca8e45258ba1937db8b18661/main/libpsl) |
| `libssl3-3.5.9-r0` | Apache-2.0 | [openssl](https://github.com/alpinelinux/aports/tree/b6d0d5c5639c0034e9073c39e9ff139e28e71818/main/openssl) |
| `libunistring-1.3-r0` | GPL-2.0-or-later OR LGPL-3.0-or-later | [libunistring](https://github.com/alpinelinux/aports/tree/22200a467cea998010743cc288889dbde0496d4a/main/libunistring) |
| `mpdecimal-4.0.1-r0` | BSD-2-Clause | [mpdecimal](https://github.com/alpinelinux/aports/tree/c0519b85456e9b838e3142e1d233aab0b433b476/main/mpdecimal) |
| `ncurses-terminfo-base-6.5_p20250503-r0` | X11 | [ncurses](https://github.com/alpinelinux/aports/tree/3fefbe8dda8b3e85458edb190e2f3a69ad16035c/main/ncurses) |
| `nghttp2-libs-1.69.0-r0` | MIT | [nghttp2](https://github.com/alpinelinux/aports/tree/87de39802b2c34c9a7c62a52b3e39e05af1c974e/main/nghttp2) |
| `pcre2-10.46-r1` | BSD-3-Clause | [pcre2](https://github.com/alpinelinux/aports/tree/f5ca111ded52f3c1f4298b09e118af54fba80aa1/main/pcre2) |
| `python3-3.12.16-r0` | PSF-2.0 | [python3](https://github.com/alpinelinux/aports/tree/712199df117586aee4a5a8138360636deafcae27/main/python3) |
| `sqlite-libs-3.49.2-r1` | blessing | [sqlite](https://github.com/alpinelinux/aports/tree/dac9cea7503a4e9b84d647aab2492d733ac4ac8c/main/sqlite) |
| `xz-libs-5.8.4-r0` | GPL-2.0-or-later AND 0BSD AND Public-Domain AND LGPL-2.1-or-later | [xz](https://github.com/alpinelinux/aports/tree/4ad8da6dc8e2b7ed46653b9844835babc3a166ae/main/xz) |
| `zlib-1.4-r0` | Zlib | [zlib](https://github.com/alpinelinux/aports/tree/a01d2885b6dc5443913a4a40f3689984ab66e7bb/main/zlib) |
| `zstd-libs-1.5.7-r0` | BSD-3-Clause OR GPL-2.0-or-later | [zstd](https://github.com/alpinelinux/aports/tree/fc7fd35c7bf99156ae31962877c074f679f45b73/main/zstd) |
| `libgcc-14.2.0-r6` | GPL-2.0-or-later AND LGPL-2.1-or-later | [gcc](https://github.com/alpinelinux/aports/tree/fbf60319be3bbaf6dd32ef55cc6fb7189e05c266/main/gcc) |
| `libstdc++-14.2.0-r6` | GPL-2.0-or-later AND LGPL-2.1-or-later | [gcc](https://github.com/alpinelinux/aports/tree/fbf60319be3bbaf6dd32ef55cc6fb7189e05c266/main/gcc) |
| `bash-5.2.37-r0` | GPL-3.0-or-later | [bash](https://github.com/alpinelinux/aports/tree/dfdce3cefb431614e410ac9bc3665d33ea45020c/main/bash) |
| `readline-8.2.13-r1` | GPL-3.0-or-later | [readline](https://github.com/alpinelinux/aports/tree/be0833caee3020f089f02c5d7223e971a9a11ffb/main/readline) |
| `libncursesw-6.5_p20250503-r0` | X11 | [ncurses](https://github.com/alpinelinux/aports/tree/3fefbe8dda8b3e85458edb190e2f3a69ad16035c/main/ncurses) |
| `busybox-1.37.0-r20` | GPL-2.0-only | [busybox](https://github.com/alpinelinux/aports/tree/2e97d754a30d558f15524b8e422303c8a96832df/main/busybox) |
| `musl-1.2.5-r13` | MIT | [musl](https://github.com/alpinelinux/aports/tree/ddaf59b84bc6983a37d6e24d2210c2c4791642bb/main/musl) |

打包目录内的 APKBUILD 列出对应上游源码归档、补丁、校验值及构建步骤。本机源码交付包已收齐 27 份 APKBUILD 和其中列出的 265 份输入，逐一通过 APKBUILD 的 SHA-512 校验。

## PRoot

在历史构建目录中找到与发布输入相符的源码树。PRoot 0.4.23 树保留的 core 输出与 `libproot_core.so` 一致，使用 DevEco SDK 和仓库中的预加载编译命令从同一树重新编译的 preloader 与 `libproot_preloader.so` 一致。Termux PRoot 早期构建树的 `src/proot` 和 `src/loader/loader` 分别与 `libproot_exec.so` 和 `libproot_loader.so` 一致。上述比较以 [发布输入 SHA-256](build-inputs.sha256) 为准。talloc 2.4.3 官方源码归档也与历史构建输入完全相同。 [Termux 固定提交](https://github.com/termux/proot/tree/60485d2646c1e09105099772da4a20deda8d020d) · [Termony 鸿蒙移植](https://github.com/TermonyHQ/Termony/tree/2fe84795201dbe14a586819f7de641db6b6c18b7/build-hnp) · [talloc 官方源码](https://www.samba.org/ftp/talloc/)

本机交付包 `dsh-mh-0.4.26-alpine-proot-source.tar.gz` 包含两份历史 PRoot 源码树、talloc 官方源码、原始上游源码、移植补丁和构建脚本。已验证完整归档可读取。仍需落实对外提供位置、随包版权声明，以及其他组件的对应源码或许可证。Linux guest Node 和 HarmonyOS 原生 Node 分别核对。 [Linux Node 验证记录](archive/harmonyos-poc/proot-full-validation.md) · [Node 固定源码](https://github.com/nodejs/node/tree/d89bb1b482fa09245c4f2cbb3b5b6a70bea6deaf)

## Node.js、图像库和 npm 组件

- 两个 Node.js 运行时均为 24.14.1。鸿蒙原生 `libnode.so` 和 Alpine 的 `libguest_node.so` 分别匹配历史目录的已签名制品和 Unofficial Builds 归档中的 `bin/node`。原生构建的官方源码归档按历史清单校验，八个本地补丁在独立目录通过源码准备脚本。此轮未重编整套 Node。 [Node.js 官方源码](https://nodejs.org/dist/v24.14.1/) · [Node.js Unofficial Builds](https://unofficial-builds.nodejs.org/download/release/v24.14.1/)
- 从 npm 注册表按版本重新取得七个随包原生二进制。验证发布者的完整性摘要后，逐项匹配 sharp、libvips、ripgrep、Koffi、DSH System、Landlock 和 require-builtin 的发布输入。用原始 pnpm 11.28.5 发布归档和本仓库脚本重打包，450 个文件与实际分发的 pnpm 层逐字节一致。 [pnpm 打包脚本](../runtime/harmonyos/packaging/package-plugin-runtime.py)
- libvips 8.18.7 与 sharp-libvips v1.3.4 发布归档的 ARM64 musl 文件完全一致。已归档对应构建源码、libvips 上游源码和第三方声明。另行归档了固定版本 POSIX 构建脚本中的全部 33 个源码或补丁下载项，逐项记录 SHA-256。已在独立 0.4.27 Release HAP 中验证，替换暂存工程的 `entry/libs/arm64-v8a/libguest_vips.so` 后，替换 ELF 的 Build ID 保留在打包结果中。原始库和替换库的图片运行验证均被发行包的 PRoot 启动失败阻断，替换库的运行验收仍待完成。 [sharp-libvips v1.3.4](https://github.com/lovell/sharp-libvips/releases/tag/v1.3.4) · [libvips v8.18.7](https://github.com/libvips/libvips/releases/tag/v8.18.7)

本机归档 `dsh-mh-0.4.26-node-npm-provenance.tar.gz` 和相邻的 SHA-256 文件保存在 `.build/artifacts/harmonyos-appgallery/`。归档包含原生 Node 源码及历史构建脚本、Linux musl 原始构建归档、核验过的 npm 发布物、sharp 和 libvips 源码及构建记录。

本机归档 `dsh-mh-0.4.26-libvips-build-inputs.tar.gz` 包含上述 33 个下载项、来源和摘要清单、构建脚本及第三方声明。归档已校验可读取。按固定 sharp-libvips 构建仓库的流程执行 `./build.sh linuxmusl-arm64v8`，从输出的 `sharp-libvips-linuxmusl-arm64v8.tar.gz` 中提取 `lib/libvips-cpp.so.8.18.7`。在独立测试包的暂存工程中替换上述输入后运行 Hvigor，随后检查 HAP 里的 ELF 和图片上传。上游完整重编仍待验证。

商店构建在「设置 → 通用 → 开源软件声明」展示 DSH、dshm、Node.js、PRoot、sharp、ripgrep、Koffi、DSH System、require-builtin、pnpm 的许可证，以及固定版本的 libvips 第三方声明。许可证直接从固定源码或发布层提取。libvips 声明来自 sharp-libvips v1.3.4 发布的构建提交。

「Alpine Linux 3.22」入口显示 32 个随包版本及对应的固定打包源码，并按 27 个上游项目分别展示归档中的许可或版权文本。SQLite 展示源码声明，CA 证书包展示证书数据及打包脚本附带的许可声明。
