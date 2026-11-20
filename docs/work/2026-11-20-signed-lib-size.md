# 常用动态库签入 HAP 的体积评估（2026-11-20）

基线：HAP 已签入的库来自 `docs/guest-tools-lock.json`，已经覆盖：openssl/libssl/libcrypto、zlib、zstd、xz(lzma)、bz2、brotli、c-ares、nghttp2、libcurl、pcre2、sqlite、expat、libffi、libidn2、libpsl、libunistring、libstdc++、libgcc_s、ncurses 部分等。因此"补齐常用动态库"的增量比直觉小。

估算方法：从 Alpine v3.20 aarch64 APK 中提取对应 `.so`，统计原始大小与 zlib 压缩大小（HAP 内 native 库以压缩形式计入包体，实际 HAP 增量≈压缩后大小，误差约 ±15%）。

## Tier A：最常用（jq / 归档 / 压缩类工具的依赖）

| 库 | 来源包 | 原始 | 压缩 |
| --- | --- | ---: | ---: |
| libjq.so.1 | jq | 329,480 | ~100,000 |
| libonig.so.5 | oniguruma | 617,488 | 189,191 |
| liblz4.so.1 | lz4-libs | 132,800 | 65,713 |
| liblzo2.so.2 | lzo | 198,336 | 74,879 |
| libarchive.so.13 | libarchive | 722,816 | 326,678 |
| libacl.so.1 | libacl | 67,344 | 13,541 |
| libattr.so.1 | libattr | 67,344 | 7,043 |
| libyaml-0.so.2 | yaml | 132,824 | 43,158 |
| **合计** | | **~2.27 MB** | **~0.82 MB** |

Tier A 可让"下载的 jq、bsdtar/libarchive 系、zstd/lz4 压缩工具、带 yaml 的 CLI"等动态工具直接跑（jq 二进制本身可运行时下载，无需打包）。

## Tier B：再加图像/XML 类工具

| 库 | 来源包 | 原始 | 压缩 |
| --- | --- | ---: | ---: |
| libpng16.so.16 | libpng | 198,576 | 96,234 |
| libjpeg.so.8 | libjpeg-turbo | 526,248 | 253,654 |
| libwebp.so.7 | libwebp | 329,608 | 190,739 |
| libtiff.so.6 | tiff | 460,736 | 161,100 |
| libxml2.so.2 | libxml2 | 1,248,632 | 519,469 |
| **小计** | | **~2.76 MB** | **~1.22 MB** |

Tier A+B 合计：**原始 ~5.03 MB，HAP 增量约 ~2.0 MB（±15%）**。

## Tier C：编译器运行时（仅 libgomp/libatomic，不含 gcc 本体）

libgomp ~330 KB（压缩 ~139 KB）+ libatomic ~67 KB（压缩 ~9 KB）→ 原始 ~0.40 MB，压缩 ~0.15 MB。

Tier A+B+C：**原始 ~5.43 MB，HAP 增量约 ~2.2 MB（±15%）**。

## 结论

- 当前 signed HAP 约 **772 MB**；常用动态库补齐（Tier A+B）预计只增加 **约 2 MB（0.3%）**，设备安装占用增加约 **5 MB**。
- 不需要把完整工具链塞进去：库是主要缺口，工具本身仍可运行时下载（exec 已透明）。
- 如果未来要支持 gcc/完整开发工具链，那才是几十 MB 级（gcc 包 ~62 MB 原始、~25 MB 压缩），与本次 exec 能力无关。
- 许可证：新增库涉及 BSD/MIT/Zlib/Apache-2.0 等，需在 `NOTICE`/`LICENSES` 增补；libgomp 属 GPL runtime exception，需注明。

## 实施方式（下一步）

1. 在 `docs/guest-tools-lock.json` 增加 Tier A（再按需 Tier B）包及 SHA-256；
2. `runtime/harmonyos/packaging/package-shell-tools.py` 会自动把包内 `usr/lib/*.so` 打包为签名 `libguest_cli_*.so` 并生成绑定（现有机制）；
3. 重新构建自建 HAP，实测 HAP 体积增量并跑动态工具验证（jq、libarchive 类）。
