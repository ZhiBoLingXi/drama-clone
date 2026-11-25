#!/usr/bin/env bash
# 打两个包到 dist/：纯技能 zip，和 WorkBuddy 专家包 zip（技能从本仓库现拷，不用旧副本）。
set -euo pipefail
cd "$(dirname "$0")"

ver=$(sed -n 's/^  version: *//p' SKILL.md | head -1)
[ -n "$ver" ] || { echo "SKILL.md 里没找到 version" >&2; exit 1; }
SKILL_FILES=(SKILL.md references scripts templates library requirements-docx.txt)

rm -rf dist/build workbuddy/skills
mkdir -p dist/build/drama-clone workbuddy/skills/drama-clone
cp -R "${SKILL_FILES[@]}" dist/build/drama-clone/
cp -R "${SKILL_FILES[@]}" workbuddy/skills/drama-clone/
find dist/build workbuddy/skills \( -name __pycache__ -o -name .DS_Store \) -prune -exec rm -rf {} +

# 源 SKILL.md 按 Agent Skills 规范把展示字段放在 metadata 下；WorkBuddy 市场只认顶层字段，打包时提到顶层。
flatten() {
  python3 -B - "$1" <<'PY'
import sys
p = sys.argv[1]
lines = open(p, encoding="utf-8").read().split("\n")
end = lines.index("---", 1)
head, out, i = lines[1:end], [], 0
while i < len(head):
    if head[i] == "metadata:":
        i += 1
        while i < len(head) and (head[i].startswith("  ") or not head[i]):
            out.append(head[i][2:])
            i += 1
    else:
        out.append(head[i])
        i += 1
need = ("version:", "display_name:", "display_name_en:", "description_zh:", "description_en:")
miss = [k for k in need if not any(l.startswith(k) for l in out)]
if miss:
    sys.exit(f"{p} 拍平后缺字段：{miss}")
open(p, "w", encoding="utf-8").write("\n".join(["---", *out, *lines[end:]]))
PY
}
flatten dist/build/drama-clone/SKILL.md
flatten workbuddy/skills/drama-clone/SKILL.md

python3 -B scripts/clone_check.py --help >/dev/null  # 脚本跑不起来就不打包
python3 -B scripts/hot_rank.py --help >/dev/null

(cd dist/build && rm -f "../drama-clone-v$ver.zip" && zip -qr "../drama-clone-v$ver.zip" drama-clone)
[ -f workbuddy/avatars/expert.png ] || echo "提醒：workbuddy/avatars/expert.png 还没有，专家包上架前要补" >&2
(cd workbuddy && rm -f "../dist/drama-clone-expert-v$ver.zip" && zip -qr "../dist/drama-clone-expert-v$ver.zip" . -x '.DS_Store')
rm -rf dist/build
ls -l "dist/drama-clone-v$ver.zip" "dist/drama-clone-expert-v$ver.zip"
