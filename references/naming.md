# 目录、剧名和交付命名

一部原剧可以裂变出好几部新剧。原剧只拉一次、只提取一次，每部新剧一个文件夹，交付件按统一规则命名。

## 目录

```
<根目录>/<原剧名>/                 原剧工作区：clone_check.py init --root <根目录> --source-title <原剧名>
  source/                          原剧，所有变体共用，只拉一次
    template.json                  模板 id、库、原剧名
    extract/                       raw/（拉下来的窗口）source/ beats/ dialogue/ manifest.json corpus.txt
    beat-sheet.json beats-all.json fingerprints-all.json
  market/hot-YYYYMMDD.md           热播榜，一周内所有变体共用
  shells.md                        外壳候选：每轮一节「## 第N轮」，用户选定后写「选定：候选X」
  variants.json                    已立项的变体：编号、剧名、外壳、状态
  V01-<新剧名>/                     变体目录：clone_check.py variant 建
    variant.json                   编号、剧名、选的候选、外壳四轴、状态
    bible.md season-map.md cast.json approved-sample.txt
    out/                           任务包、正文骨架、实现表（过程文件，不交付）
    delivery/                      交付件，只放下面这几种文件
```

- **原剧名**作工作区文件夹名，去掉书名号。同一部原剧再裂变时，`init` 会按模板 id 或原剧名找到已有的工作区，不新建、不重拉。
- 拉模板中途断了，`source/extract/raw/` 里已经有的窗口不重拉，只补缺的。
- **变体编号**按立项顺序：V01、V02……文件夹名是 `V<编号>-<新剧名>`，剧名里文件系统不认的字符换成 `-`。
- 写这部新剧的所有命令都用 `--project <变体目录>`；在工作区目录上跑 `next` 是出外壳、选剧名、立项。

## 剧名

外壳选定以后，起 5 个剧名，先跑 `title-check`，过了的才拿给用户选：

```bash
python3 scripts/clone_check.py title-check --workspace <原剧工作区> 剧名1 剧名2 剧名3 剧名4 剧名5
```

脚本卡的：
- 4-16 个汉字，连标点不超过 20 个字；不带书名号和 `/ \ : * ? " < > |`。
- 不和原剧重名或互相包含，不和最近一份热播榜上的剧撞名（续季去掉「第N季」再比），不和本工作区已立项的变体重名。
- 不带原剧专名（指纹表里的人名、地名、道具和原剧说话人名）。

脚本卡不了、要自己守的：
- 卖点或反差放前面，一眼看出是什么爽：身份反差（「同学会笑我乡下养猪」）、数字（「减一斤一个亿」）、处境（「和离后我带女儿」）。
- 5 个剧名要有差别：有的走身份反差，有的走处境，有的走结果，别 5 个都是一个句式换词。
- 剧名对应这个外壳的核心爽点，不要起一个和剧情对不上的。

用户选定后立项：`python3 scripts/clone_check.py variant --workspace <原剧工作区> --title <剧名> --shell 候选X --axes '<地域行业·主角身份·底牌形式·关系载体>'`。

## 交付件

`clone_check.py deliver --project <变体目录>` 写进 `delivery/`，版本号自动加一（稿子和上一版一模一样时不出新版）：

| 文件 | 内容 |
|---|---|
| `《剧名》剧本_v<N>_<YYYYMMDD>.md` | 全季合并稿：剧名、人物小传（取自 bible.md 的「## 人物小传」）、正文，对位注释已去掉 |
| `《剧名》剧本_v<N>_<YYYYMMDD>.docx` | 同一份的 Word（需要 python-docx） |
| `《剧名》原剧对照表_v<N>.md` | 原剧和新剧逐句对照，给人审 |
| `《剧名》交付说明_v<N>.md` | 字数统计、检查结果、和其他变体的查重和撞名、哪些没做、以前的版本 |
| `《剧名》审查报告_v<N>.md` | drama-review 的报告（跑了才有，自己放进来） |

- 交付件只放这几种，过程文件留在 `out/`。
- 按反馈改稿后再跑一次 `deliver`，出 v2，旧版本留着不删，交付说明里列版本记录。
- `deliver` 只在全部集都过了 `check`、bible.md 有「## 人物小传」时才出包。
