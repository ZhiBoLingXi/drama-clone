# Agent 安装入口

仓库：https://github.com/zhibolingxi/drama-clone
技能名：`drama-clone`。技能位于仓库根目录，不存在额外的 `skills/drama-clone` 子目录。

1. 确认当前宿主的技能发现目录。Codex 为 `${CODEX_HOME:-$HOME/.codex}/skills`，Claude Code 为 `~/.claude/skills`，WorkBuddy 为 `~/.workbuddy/skills`；其他宿主遵循其本地配置。
2. 目标目录为上述目录下的 `drama-clone`。若已存在，检查其来源和本地修改；不要强制覆盖、删除或 reset。来自本仓库的干净 Git 克隆可以 `git pull --ff-only` 更新。
3. 将完整仓库克隆到目标目录：`git clone https://github.com/zhibolingxi/drama-clone.git <目标目录>`。不要只下载 SKILL.md。
4. 确认存在 `SKILL.md`、7 个 `references/*.md`、3 个 `templates/*.md` 和 2 个 `scripts/*.py`。读取 SKILL.md 的 `name` 应为 `drama-clone`。
5. 运行 `python3 <目标目录>/scripts/clone_check.py --help`，应成功列出 `sheet/build/align/fingerprint/voice/rules/dup`。这验证安装可运行，不代表已验证创作效果。
6. 不需要预装 MCP、API 密钥或模型服务。只有用户需要 Word 导出时，才按 README 安装 `requirements-docx.txt` 中的可选依赖。
7. 回报安装绝对路径、版本、验证结果和调用示例。提示按宿主要求重新加载技能或开启新会话。安装本身不启动剧本创作任务。

## Codex 自带安装器

若当前 Codex 提供 skill-installer，也可使用其脚本（脚本路径以宿主实际安装为准）：

```bash
python3 /path/to/skill-installer/scripts/install-skill-from-github.py \
  --repo zhibolingxi/drama-clone --path . --name drama-clone --method git
```

这里显式使用 Git 模式，避免部分环境的 ZIP 下载通道出现 SSL 错误；不要禁用 TLS 校验。安装器输出为技能副本，不包含 `.git`；后续更新遵循宿主安装器流程，先保留本地修改。
