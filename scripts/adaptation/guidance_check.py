#!/usr/bin/env python3
"""G1: keep the AI development guidance docs coherent.

Required files, key sections and cross-links are checked so "framework rules"
cannot silently disappear or drift while modules change.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_FILES = [
    "AGENTS.md",
    "docs/AGENTS.md",
    "docs/architecture/framework.md",
    "docs/architecture/feature-roadmap.md",
    "docs/architecture/README.md",
    "packages/dsh-host/AGENTS.md",
    "runtime/harmonyos/compat/AGENTS.md",
    "runtime/harmonyos/native/AGENTS.md",
    "runtime/harmonyos/packaging/AGENTS.md",
    "apps/harmonyos/AGENTS.md",
    "tests/smoke/AGENTS.md",
    "gates/AGENTS.md",
    "patches/AGENTS.md",
]
SECTIONS = {
    "docs/architecture/framework.md": ["分层", "所有权", "硬性不变量", "改动落点", "门禁", "已知边界"],
    "docs/architecture/feature-roadmap.md": ["能力矩阵", "新增功能的落点", "待办优先级"],
    "AGENTS.md": ["docs/architecture/framework.md", "docs/architecture/feature-roadmap.md", "完成定义", "gates/run.py"],
    "docs/AGENTS.md": ["文档分层", "写作规则", "文档验证"],
}


def main():
    failures = []
    for name in REQUIRED_FILES:
        path = ROOT / name
        if not path.is_file():
            failures.append(f"missing guidance file: {name}")
            continue
        if path.stat().st_size < 200:
            failures.append(f"guidance file too small: {name}")
        if (name.endswith("AGENTS.md") and name.startswith(("packages/", "runtime/", "apps/", "tests/", "gates/", "patches/"))
                and "## 规则" not in path.read_text()):
            failures.append(f"{name}: missing '## 规则' section")
    for name, sections in SECTIONS.items():
        path = ROOT / name
        if not path.is_file():
            continue
        text = path.read_text()
        for section in sections:
            if section not in text:
                failures.append(f"{name}: missing section {section!r}")
    architecture_readme = (ROOT / "docs/architecture/README.md").read_text()
    for link in ("framework.md", "feature-roadmap.md", "compat-layer.md", "release-runbook.md"):
        if link not in architecture_readme:
            failures.append(f"docs/architecture/README.md does not index {link}")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        return 1
    print(f"G1 guidance docs OK: {len(REQUIRED_FILES)} files, sections and indexes present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
