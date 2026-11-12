#!/usr/bin/env python3
"""校验 `.agents/skills/*`：frontmatter、name 唯一性、目录名一致性与附件路径。

用法：
    python LLM/agent/two/xAgent/scripts/validate_skills.py --root <项目根目录>

有错误时退出码为 1；仅有警告时退出码为 0。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

XAGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(XAGENT_DIR.parent))

from xAgent.settings import agent_settings  # noqa: E402
from xAgent.skills import SKILLS_DIR, SKILL_FILE, _parse_frontmatter  # noqa: E402

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-_]{0,63}$")


def validate(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    skills_root = root / SKILLS_DIR
    if not skills_root.is_dir():
        warnings.append(f"未找到技能目录：{skills_root}")
        return errors, warnings

    seen: dict[str, Path] = {}
    folders = sorted(
        (item for item in skills_root.iterdir() if item.is_dir()),
        key=lambda item: item.name.lower(),
    )
    for folder in folders:
        if folder.name.startswith("."):
            warnings.append(f"忽略临时目录：{folder.name}")
            continue
        skill_file = folder / SKILL_FILE
        if not skill_file.is_file():
            errors.append(f"{folder.name}: 缺少 {SKILL_FILE}")
            continue

        meta = _parse_frontmatter(skill_file)
        name = (meta.get("name") or "").strip()
        description = (meta.get("description") or "").strip()
        if not name:
            errors.append(f"{folder.name}: frontmatter 缺少 name")
        elif not NAME_RE.fullmatch(name):
            errors.append(
                f"{folder.name}: name={name!r} 不匹配 ^[a-z0-9][a-z0-9-_]{{0,63}}$"
            )
        elif name != folder.name:
            errors.append(f"{folder.name}: name={name!r} 与目录名不一致")
        if not description:
            errors.append(f"{folder.name}: frontmatter 缺少 description")

        if name:
            if name in seen:
                errors.append(
                    f"{folder.name}: name={name!r} 与 {seen[name].name} 重复"
                )
            else:
                seen[name] = folder

        resolved_root = folder.resolve()
        for item in folder.rglob("*"):
            if item.is_symlink():
                try:
                    target = item.resolve()
                except OSError as exc:
                    errors.append(f"{folder.name}: 无法解析符号链接 {item}: {exc}")
                    continue
                if not target.is_relative_to(resolved_root):
                    errors.append(
                        f"{folder.name}: 符号链接越界 "
                        f"{item.relative_to(folder).as_posix()} -> {target}"
                    )
            relative = item.relative_to(folder)
            if ".." in relative.parts:
                errors.append(
                    f"{folder.name}: 非法附件路径 {relative.as_posix()}"
                )

    return errors, warnings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="校验 Agent Skills 目录")
    parser.add_argument(
        "--root",
        default=".",
        help="项目根目录（包含 .agents/skills），默认当前目录",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    options = agent_settings()
    max_chars = options.get("skill_max_chars", 50000)

    errors, warnings = validate(root)
    for warning in warnings:
        print(f"[WARN] {warning}")
    for error in errors:
        print(f"[ERROR] {error}")
    print(
        f"校验完成：{len(errors)} 个错误，{len(warnings)} 个警告；"
        f"技能目录 {root / SKILLS_DIR}；单文件读取上限 {max_chars} 字符。"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
