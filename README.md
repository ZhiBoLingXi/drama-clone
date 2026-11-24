# drama-clone · 短剧高仿裂变

从逐集拉片、剧情和字幕中提取抽象节拍与台词结构，创作表达全新的短剧，并检查节拍对齐、原剧指纹词、字面重复、字数和制作规则。当前技能版本：**1.6.1**。

## 复制链接给 Agent 安装

把下面这段直接发给支持本地技能的 Agent：

> 请安装 https://github.com/zhibolingxi/drama-clone 。先阅读仓库的 INSTALL.md，按当前宿主的技能目录安装完整技能，验证 SKILL.md 和检查脚本可用，并告诉我如何调用；已有同名技能时先检查差异，不要覆盖本地修改。

只发送仓库链接时，Agent 也可从本 README 找到 [安装说明](INSTALL.md)。仓库根目录就是技能目录，必须同时安装 `SKILL.md`、`references/`、`templates/` 和 `scripts/`。

## 手动安装

需要 Git 和 Python 3。选择当前 Agent 对应的一条命令；目标目录已有内容时停止并检查差异。

```bash
# Codex
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
git clone https://github.com/zhibolingxi/drama-clone.git "${CODEX_HOME:-$HOME/.codex}/skills/drama-clone"

# Claude Code
mkdir -p "$HOME/.claude/skills"
git clone https://github.com/zhibolingxi/drama-clone.git "$HOME/.claude/skills/drama-clone"

# WorkBuddy
mkdir -p "$HOME/.workbuddy/skills"
git clone https://github.com/zhibolingxi/drama-clone.git "$HOME/.workbuddy/skills/drama-clone"
```

其他 Agent 使用宿主实际支持的技能目录。安装后重新加载技能或开启新会话；能否自动发现取决于宿主。

## 使用

示例请求：

> 使用 drama-clone，根据我提供的逐集剧情与字幕，先提取节拍表，再给我三个不同的外壳候选。选定后先写一集样集，每集全文至少 800 字，每句台词不超过 20 字。

工作流：提取节拍与指纹 → 选择外壳 → 设定圣经和全季实现地图 → 样集 → 分批正文 → 检查与交付 → 反馈修订。详细约束以 [SKILL.md](SKILL.md) 为准。

无需特定 MCP：可直接使用用户提供的拉片、集纲和字幕。有 mali-story 连接时可按技能说明读取逐集证据。没有子代理能力时顺序执行。

## 依赖与验证

核心检查只使用 Python 3 标准库，不联网。在技能目录运行：

```bash
python3 scripts/clone_check.py --help
python3 scripts/clone_check.py next --project /path/to/项目 --range 1-14   # 每一步先问它下一步做什么
python3 scripts/clone_check.py voice /path/to/正文.md --min-total 800 --max-tics 0
python3 scripts/clone_check.py rules /path/to/正文.md
```

需要导出 Word 时再安装可选依赖（建议在项目虚拟环境内）：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-docx.txt
.venv/bin/python scripts/to_docx.py /path/to/剧本.md /path/to/剧本.docx
```

检查脚本退出码：`0` 通过，`1` 输入错误，`2` 有违反项。字面查重和节拍检查只提供技术线索，不能证明剧本的原创质量或版权状态。

## 仓库结构与维护

- `SKILL.md`：技能入口与工作流。
- `references/`：节拍、台词结构、裂变、制作、编排和格式规则。
- `templates/`：提取、写作、修订任务书。
- `workbuddy/`：WorkBuddy 专家包的源文件（专家 manifest、系统提示词、mali-story 连接器声明）。
- `pack.sh`：打包。产出 `dist/drama-clone-v<版本>.zip`（纯技能）和 `dist/drama-clone-expert-v<版本>.zip`（专家包，技能从本仓库现拷）；`dist/` 和 `workbuddy/skills/` 不入库。
- `scripts/clone_check.py`：流程导航（`next`）、骨架生成（`source`/`scaffold`/`cast`/`brief`）、逐集快检（`check`）和各项单独检查。
- `scripts/to_docx.py`：Word 导出。
- `INSTALL.md`：面向安装 Agent 的操作说明。

维护源码位置为 `~/dev/skills/drama-clone`。原 `~/dev/story-script/dist/drama-clone` 已迁移，旧路径通过符号链接兼容；旧 ZIP 是历史快照，不再作为最新源。剧本、原剧字幕和项目运行产物应放在独立项目目录，不提交到本仓库。

更新已克隆的安装：先确认 `git status --short` 无本地修改，再执行 `git pull --ff-only`。本仓库保留原技能作者 MaLiAI 与版本信息；此次迁移只调整分发包装与元数据位置，未修改创作流程及检查脚本。
