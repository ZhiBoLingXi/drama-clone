# 节拍表提取

## 子代理 prompt

把下面的 prompt 交给一个 general-purpose 子代理，附上模板存盘路径和总字符数：

```
读取短剧拉片模板 JSON：<PATH>（共 <N> 字符）。它是单行长 JSON，用 python 按 read()[A:B] 每次约 8 万字符切片，读到 100%。
这是竖屏短剧《<剧名>》的逐集拆解。我要做「高仿裂变」：新剧逐集对齐它的节拍功能，但表达层全部重写。
请输出一个 JSON 文件到 <OUT>/beat-sheet.json，结构见下。

规则：
1. beats[].function 只写抽象功能，例如「主角当众被羞辱、无人相信」「观众先知主角底牌、角色不知」「反派小胜」「主角借第三方小反击」。
   不许出现原剧任何人名、地名、组织名、具体道具。用人设功能位代称人物（主角 / 压迫者A / 帮手B / 背叛者C …）。
2. emotion 取 -3（极憋屈）到 +3（极爽）的整数。
3. payoff 取：即时打脸 / 倒计时引信 / 信息差反讽 / 民心审判 / 因果回旋镖 / 降维破局 / 数字对称报应 / 情感兑现 / 无。
4. hook 写本集结尾钩子的抽象形状。
5. 模板里没有的集，在 gaps 里列出集号，不要编。
6. fingerprints 穷举原剧专名与名场面，terms 照抄原文（含错别字变体），这是要避开的清单。
7. roles 列出人设功能位及其在原剧里对应的人物（原名只放在 sourceName，节拍里不要出现）。
只做提取，不写集纲或正文。
```

## JSON 结构

```json
{
  "source": "原剧名",
  "totalEpisodes": 80,
  "engine": "品类 + 核心情绪引擎，一句话",
  "mainSpring": {"what": "总弹簧", "episode": 62},
  "roles": [
    {"id": "R1", "function": "主角", "sourceName": "原剧人名"},
    {"id": "R2", "function": "压迫者：势利亲家", "sourceName": "原剧人名"}
  ],
  "episodes": [
    {
      "ep": 1,
      "beats": [
        {"id": "E1-B1", "function": "主角当众被羞辱、无人相信", "roles": ["R1", "R2"], "emotion": -2, "payoff": "无"},
        {"id": "E1-B2", "function": "观众先知主角底牌，角色不知", "roles": ["R1"], "emotion": 1, "payoff": "信息差反讽"}
      ],
      "hook": "底牌的一角被第三方看见",
      "climax": false
    }
  ],
  "gaps": [],
  "fingerprints": [
    {"id": "F1", "kind": "人名", "terms": ["原名", "错字变体"]},
    {"id": "F9", "kind": "名场面", "episodes": [12], "desc": "一句话描述原场面", "terms": ["标志道具", "标志台词片段"]}
  ]
}
```

`kind` 取：人名 / 地名 / 组织 / 道具 / 口头禅 / 名场面 / 其他。`climax: true` 标 ★小高潮集。
