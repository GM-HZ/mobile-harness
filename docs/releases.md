# 版本记录

## 0.4.4

现存 PRoot 源码基线。启动时探测 seccomp 追踪加速，Mate 60 实际回退到兼容模式。引擎由应用进程持有，Home 重进复用。内置 ESM 源码索引和回环鉴权路径优化已加入。真机约 219.8 秒显示聊天页。

签名 HAP SHA-256 为 `ecf3229ca8d566bcc96e790919684e17ad35fc3ffaccb2025b37874fc8b0373a`。

## 0.4.6 原生启动试验

鸿蒙原生 Node 24.14.1 启动官方 DSH Web Host，PRoot 负责同工作区的固定 Bash 探针。修复 PRoot 等待子进程被信号中断后的处理。Mate 60 已解包冷启动 10.2 秒，独立模拟器全新安装首次启动 15.4 秒。探针模式使用独立账号和会话目录。

签名 HAP SHA-256 为 `43b6b29e06f7e9d8cb98341ddbfda641e172b52a4789c1df1580f13e30320985`。 [计时证据](evidence/native-web-comparison-0.4.6.json)
