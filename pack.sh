#!/usr/bin/env bash
# 打两个包到 dist/：纯技能 zip，和 WorkBuddy 专家包 zip（技能从本仓库现拷，不用旧副本）。
set -euo pipefail
cd "$(dirname "$0")"

ver=$(sed -n 's/^  version: *//p' SKILL.md | head -1)
[ -n "$ver" ] || { echo "SKILL.md 里没找到 version" >&2; exit 1; }
SKILL_FILES=(SKILL.md references scripts templates requirements-docx.txt)

rm -rf dist/build workbuddy/skills
mkdir -p dist/build/drama-clone workbuddy/skills/drama-clone
cp -R "${SKILL_FILES[@]}" dist/build/drama-clone/
cp -R "${SKILL_FILES[@]}" workbuddy/skills/drama-clone/
find dist/build workbuddy/skills \( -name __pycache__ -o -name .DS_Store \) -prune -exec rm -rf {} +

python3 -B scripts/clone_check.py --help >/dev/null  # 脚本跑不起来就不打包

(cd dist/build && rm -f "../drama-clone-v$ver.zip" && zip -qr "../drama-clone-v$ver.zip" drama-clone)
[ -f workbuddy/avatars/expert.png ] || echo "提醒：workbuddy/avatars/expert.png 还没有，专家包上架前要补" >&2
(cd workbuddy && rm -f "../dist/drama-clone-expert-v$ver.zip" && zip -qr "../dist/drama-clone-expert-v$ver.zip" . -x '.DS_Store')
rm -rf dist/build
ls -l "dist/drama-clone-v$ver.zip" "dist/drama-clone-expert-v$ver.zip"
