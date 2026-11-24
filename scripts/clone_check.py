#!/usr/bin/env python3
"""DramaClone 检查工具：节拍表校验、节拍对齐、指纹扫描。只用标准库，不联网。

  clone_check.py source <模板.json|逐集evidence目录> --out extract/
  clone_check.py sheet <beat-sheet.json> [--manifest extract/manifest.json]
  clone_check.py align <beat-sheet.json> <集纲.md> [--min 0.85]
  clone_check.py fingerprint <beat-sheet.json> <稿件.md> [--ignore 词1,词2]
  clone_check.py voice <正文.md> [--min-total N] [--min-speech N] [--max-speech N] [--max-tics N]
  clone_check.py rules <正文.md> [--max-speakers 4] [--max-han 20] [--require-annotation]
  clone_check.py dup <新稿.md> <原剧语料.txt> [--k 8]
  clone_check.py build <extract目录> <beat-sheet.json> --out-beats beats-all.json --out-fp fingerprints-all.json
  clone_check.py gate <正文.md> --extract extract/ --sheet beats-all.json --impl 实现表.md [--pair-out 对照.md]
  clone_check.py presence <正文.md> --extract extract/ --sheet beats-all.json [--impl 实现表.md]

退出码：0 通过；1 输入错误；2 有违反项。输出为 JSON。
"""
import argparse
import hashlib
import json
import os
import re
import sys

CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9}
EP_HEAD = re.compile(r"^#{1,4}\s*第\s*([0-9一二两三四五六七八九十百零]+)\s*集", re.M)
BEAT_LINE = re.compile(r"对标节拍\s*[:：]\s*(.+)")
BEAT_ID = re.compile(r"E\d+-B\d+")
PAYOFFS = {"即时打脸", "倒计时引信", "信息差反讽", "民心审判", "因果回旋镖",
           "降维破局", "数字对称报应", "情感兑现", "无"}
KINDS = {"人名", "地名", "组织", "道具", "口头禅", "名场面", "其他"}


def cn_to_int(s):
    if s.isdigit():
        return int(s)
    total, cur = 0, 0
    for ch in s:
        if ch == "百":
            total += (cur or 1) * 100
            cur = 0
        elif ch == "十":
            total += (cur or 1) * 10
            cur = 0
        else:
            cur = CN_NUM[ch]
    return total + cur


def load_sheet(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


COMMENT = re.compile(r"^\s*<!--.*-->\s*$", re.M)


def split_episodes(text):
    """返回 {集号: 该集文本}。骨架里的 <!-- 对位注释 --> 不算正文，各项检查都看不到它。"""
    text = COMMENT.sub("", text)
    heads = list(EP_HEAD.finditer(text))
    out = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out[cn_to_int(m.group(1))] = text[m.start():end]
    return out


def name_variants(name):
    """三字人名补上去姓的两字名：「林旭白」也要拦「旭白」。"""
    out = [name]
    if len(name) == 3 and re.fullmatch(r"[\u4e00-\u9fff]+", name):
        out.append(name[1:])
    return out


def fingerprint_terms(sheet, manifest=None):
    terms = {}
    for fp in sheet.get("fingerprints", []):
        for t in fp.get("terms", []):
            t = t.strip()
            if len(t) >= 2:
                for v in (name_variants(t) if fp.get("kind") == "人名" else [t]):
                    terms.setdefault(v, fp.get("id", "?"))
    names = [(r.get("sourceName") or "").strip() for r in sheet.get("roles", [])]
    names += (manifest or {}).get("names", [])
    for name in names:
        if len(name) >= 2 and name not in GENERIC_ROLES:
            for v in name_variants(name):
                terms.setdefault(v, "F-NAMES")
    return terms


def turn_coverage(n, beats, total_turns):
    """每拍用 turns:[起,止] 认领原剧台词轮次。全部轮次都要被认领、按顺序、不重叠，丢拍就出不来。"""
    if not total_turns:
        return []
    out, nxt = [], 1
    for b in beats:
        t = b.get("turns")
        if t is None:
            continue  # 纯画面拍（没台词）可以不认领
        a, z = t
        if a != nxt:
            out.append(f"{b.get('id')}：从第 {a} 轮开始，但上一拍停在第 {nxt - 1} 轮（{'漏了' if a > nxt else '重叠了'}）")
        nxt = z + 1
    if nxt <= total_turns:
        out.append(f"第{n}集：原剧台词第 {nxt}-{total_turns} 轮没有节拍认领")
    return out


def load_manifest(path):
    return load_sheet(path) if path else None


def cmd_sheet(args):
    sheet = load_sheet(args.sheet)
    manifest = load_manifest(args.manifest)
    problems = []
    terms = fingerprint_terms(sheet, manifest)
    role_ids = {r.get("id") for r in sheet.get("roles", [])}
    seen = set()
    for ep in sheet.get("episodes", []):
        n = ep.get("ep")
        if n in seen:
            problems.append(f"第{n}集重复")
        seen.add(n)
        if not ep.get("beats"):
            problems.append(f"第{n}集没有节拍")
        elif len(ep["beats"]) < args.min_beats:
            problems.append(f"第{n}集只有 {len(ep['beats'])} 个节拍，至少 {args.min_beats} 个；太粗的节拍表让对齐率失去意义")
        if not (ep.get("hook") or "").strip():
            problems.append(f"第{n}集没写 hook")
        if manifest and str(n) in manifest.get("episodes", {}):
            problems += turn_coverage(n, ep.get("beats", []), manifest["episodes"][str(n)]["turns"])
        for b in ep.get("beats", []):
            bid = b.get("id", "")
            if not re.fullmatch(rf"E{n}-B\d+", bid):
                problems.append(f"{bid or '无id'}：id 应为 E{n}-B<序号>")
            fn = b.get("function", "")
            if not fn:
                problems.append(f"{bid}：缺 function")
            leaked = [t for t in terms if t in fn]
            if leaked:
                problems.append(f"{bid}：节拍功能里混进原剧专名 {leaked}")
            if b.get("payoff") not in PAYOFFS:
                problems.append(f"{bid}：payoff「{b.get('payoff')}」不在取值表")
            e = b.get("emotion")
            if not isinstance(e, int) or not -3 <= e <= 3:
                problems.append(f"{bid}：emotion 应为 -3..3 的整数")
            for r in b.get("roles", []):
                if r not in role_ids:
                    problems.append(f"{bid}：roles 里的 {r} 不在 roles 表")
        leaked_hook = [t for t in terms if t in ep.get("hook", "")]
        if leaked_hook:
            problems.append(f"第{n}集 hook 混进原剧专名 {leaked_hook}")
    for fp in sheet.get("fingerprints", []):
        if fp.get("kind") not in KINDS:
            problems.append(f"{fp.get('id')}：kind「{fp.get('kind')}」不在取值表")
    total = sheet.get("totalEpisodes")
    gaps = set(sheet.get("gaps", []))
    lo, hi = (1, total) if not args.range else map(int, args.range.split("-"))
    if isinstance(total, int):
        missing = [i for i in range(lo, min(hi, total) + 1) if i not in seen and i not in gaps]
        if missing:
            problems.append(f"既不在 episodes 也不在 gaps 的集：{missing}")
    if manifest:
        real_gaps = set(manifest.get("gaps", []))
        fake = sorted(gaps - real_gaps)
        if fake:
            problems.append(f"这些集原剧有数据，却被标成缺集：{fake}。没提取的集不能塞进 gaps")
        unmarked = sorted(g for g in real_gaps - gaps - seen if lo <= g <= hi)
        if unmarked:
            problems.append(f"原剧确实缺的集没标进 gaps：{unmarked}")
        bogus = sorted(seen & real_gaps)
        if bogus:
            problems.append(f"原剧没有数据的集却写了节拍（脑补）：{bogus}")
    elif not sheet.get("builtFrom"):
        problems.append("没给 --manifest，也不是 build 合成的节拍表，gaps 和节拍来源都核不了")
    report = {"episodes": len(seen), "beats": sum(len(e.get("beats", [])) for e in sheet.get("episodes", [])),
              "gaps": sorted(gaps), "fingerprintTerms": len(terms), "problems": problems,
              "passed": not problems}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not problems else 2


def cmd_align(args):
    sheet = load_sheet(args.sheet)
    with open(args.draft, encoding="utf-8") as f:
        eps = split_episodes(f.read())
    src = {e["ep"]: [b["id"] for b in e.get("beats", [])] for e in sheet.get("episodes", [])}
    per_ep, all_used, used_by_ep, problems = [], {}, {}, []
    for n in sorted(eps):
        m = BEAT_LINE.search(eps[n])
        used = used_by_ep[n] = BEAT_ID.findall(m.group(1)) if m else []
        added = bool(m and "新增" in m.group(1))
        if not m:
            problems.append(f"第{n}集缺「对标节拍」行")
        for b in used:
            all_used.setdefault(b, []).append(n)
        expected = src.get(n, [])
        covered = [b for b in expected if b in used]
        foreign = [b for b in used if b not in expected]
        per_ep.append({"ep": n, "expected": len(expected), "covered": len(covered),
                       "missing": [b for b in expected if b not in used],
                       "fromOtherEpisodes": foreign, "added": added})
    in_range = [n for n in src if n in eps]
    exp_total = sum(len(src[n]) for n in in_range)
    cov_total = sum(p["covered"] for p in per_ep)
    rate = cov_total / exp_total if exp_total else None
    order = [int(b.split("-")[0][1:]) for n in sorted(eps) for b in used_by_ep[n]]
    out_of_order = sum(1 for a, b in zip(order, order[1:]) if b < a)
    dup = {b: ns for b, ns in all_used.items() if len(ns) > 1}
    unknown = sorted(b for b in all_used if not any(b in v for v in src.values()))
    if unknown:
        problems.append(f"节拍表里不存在的 id：{unknown}")
    if rate is not None and rate < args.min:
        problems.append(f"对齐率 {rate:.0%} 低于 {args.min:.0%}")
    report = {"episodesChecked": sorted(eps), "alignmentRate": round(rate, 3) if rate is not None else None,
              "outOfOrderSteps": out_of_order, "reusedBeats": dup, "perEpisode": per_ep,
              "problems": problems, "passed": not problems}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not problems else 2


def cmd_fingerprint(args):
    sheet = load_sheet(args.sheet)
    with open(args.draft, encoding="utf-8") as f:
        text = COMMENT.sub("", f.read())
    ignore = {t for t in (args.ignore or "").split(",") if t}
    eps = split_episodes(text) or {0: text}
    first = EP_HEAD.search(text)
    if first and first.start() > 0:
        eps[0] = text[:first.start()]  # 人物小传等集前内容也要扫
    terms = fingerprint_terms(sheet, load_manifest(args.manifest))
    hits = []
    for term, fid in terms.items():
        if term in ignore:
            continue
        for n, body in eps.items():
            for m in re.finditer(re.escape(term), body):
                s = max(0, m.start() - 12)
                hits.append({"term": term, "fingerprint": fid, "ep": n,
                             "context": body[s:m.end() + 12].replace("\n", " ")})
    report = {"terms": len(set(terms) - ignore), "hits": hits,
              "ignored": sorted(ignore), "passed": not hits}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not hits else 2


SPEECH = re.compile(r"^([^△场人#\s][^：（]{0,20})(（[^）]*）)?：(.*)$")
AI_TICS = ["像", "如同", "仿佛", "宛如", "等于", "意味着", "象征", "一字一顿"]
# 括注和 △ 里都算：文学腔、心理旁白、“一丝/格外/显得”这类虚写
AI_TICS_ANY = ["仿佛", "如同", "宛如", "像是", "似乎", "心理侧写", "难以察觉", "闪过一丝", "掠过一丝", "一丝弧度", "格外", "显得",
               "眼底", "嘴角勾起", "唇角", "意味深长", "空气凝固", "空气中弥漫"]
HAN = re.compile("[一-鿿]")
# 偷懒的占位写法：长批次写到后面，模型常用“（以下略）”“同上”“此处省略三轮争吵”代替正文。命中一处这集就不算写完。
# 单个“略”只在前面是指代词或标点、后面收尾时才算，括注里的“略一迟疑”“略带哭腔”、台词里的“策略”“领略”都不拦。
PLACEHOLDER = re.compile(
    r"(?:以下|此处|其余|余下|中间|后续|下文|后文|具体|台词|对白|内容|细节|过程|[下后]|^|[（(【\[…。，\s])略(?=[）)】\]。，、…\s]|$)"
    r"|省略(?!号)|从略|(?:同上|同前)(?![一面任来去天年次级])|以此类推|依此类推|若干(?:轮|句|回合|行|场)"
    r"|(?:以下|后续|下同|其余|余下)同理|篇幅(?:所限|原因|有限)|限于篇幅|不再赘述|不一一(?:列出|写出|展开|赘述)"
    r"|未完待续|待补|待写|TODO|TBD|(?:同|参照|参考|照搬|照)第\s*[0-9一二两三四五六七八九十百]+\s*集"
    r"|^\s*(?:…+|\.{3,}|。{3,}|\[\.\.\.\])\s*$", re.M)


# 套路反应：同一种反应全季反复用，是 AI 稿最显眼的味道。实测一部 AI 写的 94 集，「攥着/攥紧」出现在 60 集，「冷笑」25 集。
# 规则：同一组 10 集内只用一次，同一集里只用一次。
STOCK_REACTIONS = {
    "攥紧": "攥紧|攥着|攥住|握紧拳|捏紧", "冷笑": "冷笑|嗤笑|冷哼", "愣住": "愣住|一愣|愣在|怔住|怔了",
    "叹气": "叹了口气|叹口气|长叹", "脸一沉": "脸一沉|脸色一沉|沉下脸", "脸白": "脸色一白|脸色煞白|脸色发白|脸白了",
    "喉结": "喉结", "咬牙": "咬牙|咬紧牙", "手抖": "手一抖|手抖", "倒吸凉气": "倒吸一口|倒吸了口|凉气",
    "后退": "后退一步|连连后退|退了一步|往后退", "苦笑": "苦笑", "瞪眼": "瞪大|瞪圆", "瘫坐": "瘫坐|瘫软|瘫在",
    "红眼眶": "眼眶一红|眼眶泛红|红了眼眶|眼圈一红", "深吸气": "深吸一口气|深吸了口气", "沉默": "沉默片刻|沉默了几秒|沉默半晌",
    "身子一僵": "身子一僵|浑身一僵|僵在原地|浑身一震", "顿了顿": "顿了顿",
}
STOCK_RE = {k: re.compile(v) for k, v in STOCK_REACTIONS.items()}
STOCK_GAP = 10


def stock_uses(text):
    """{组名: 命中次数}，只看 △ 行和括注：动作和神态才是套路反应出没的地方。"""
    out = {}
    for l in text.splitlines():
        s = l.strip()
        spots = [s] if s.startswith("△") else re.findall(r"（[^）]*）", s)
        for spot in spots:
            for k, rx in STOCK_RE.items():
                n = len(rx.findall(spot))
                if n:
                    out[k] = out.get(k, 0) + n
    return out


def season_stock(out_dir, skip=()):
    """同目录所有正文里每组套路反应用在哪几集：{组名: [集号…]}。"""
    import glob
    used = {}
    for p in sorted(glob.glob(os.path.join(out_dir, "draft-*.md"))):
        if os.path.abspath(p) in skip:
            continue
        with open(p, encoding="utf-8") as f:
            for n, body in split_episodes(f.read()).items():
                for k in stock_uses(body):
                    used.setdefault(k, set()).add(n)
    return {k: sorted(v) for k, v in used.items()}


def placeholders(lines):
    return [(m.group(0).strip() or "……", l.strip()[:30]) for l in lines for m in [PLACEHOLDER.search(l)] if m]


def episode_stats(n, text):
    lines = text.splitlines()
    speech = [m for m in (SPEECH.match(l) for l in lines) if m]
    speech_han = sum(len(HAN.findall(re.sub(r"（[^）]*）", "", m.group(3)))) for m in speech)
    # 全文字数：本集正文里的全部汉字（场头、人物行、△、括注、台词都算），即用户和客户口中的“剧本字数”
    body = "\n".join(l for l in lines if not EP_HEAD.match(l))
    parens = [m.group(2) for m in speech if m.group(2)]
    run, max_run, prev = 0, 0, None
    for l in lines:
        m = SPEECH.match(l)
        if m:
            run = run + 1 if m.group(1) == prev else 1
            prev = m.group(1)
            max_run = max(max_run, run)
        elif l.strip():
            prev, run = None, 0
    tics = [(t, l.strip()[:30]) for l in lines if l.startswith("△") for t in AI_TICS if t in l]
    tics += [(t, l.strip()[:30]) for l in lines for t in AI_TICS_ANY
             if t in l and not (l.startswith("△") and t in AI_TICS)]
    return {"ep": n, "scenes": sum(1 for l in lines if l.startswith("场")),
            "totalHan": len(HAN.findall(body)), "speechLines": len(speech), "speechHan": speech_han,
            "avgHanPerLine": round(speech_han / len(speech), 1) if speech else 0,
            "osLines": sum(1 for m in speech if "OS" in (m.group(2) or "")),
            "annotatedRatio": round(len(parens) / len(speech), 2) if speech else 0,
            # 括注全是“（甲，乙）”两段式的比例；接近 1 说明括注在套公式，读起来机械
            "twoPartParenRatio": round(sum(1 for p in parens if p.count("，") == 1) / len(parens), 2) if parens else 0,
            # 同一人中间不插动作连说的最多行数；长句硬拆成 4 行、行行一个括注，读起来是机器在填表
            "maxSameSpeakerRun": max_run,
            "aiTics": tics,
            "placeholders": placeholders(l for l in lines if not EP_HEAD.match(l))}


def cmd_voice(args):
    with open(args.draft, encoding="utf-8") as f:
        eps = split_episodes(f.read())
    if not eps:
        print(json.dumps({"error": "没找到 `# 第N集` 标题，按集统计不了"}, ensure_ascii=False))
        return 1
    rows = [episode_stats(n, eps[n]) for n in sorted(eps)]
    gated = any(v is not None for v in (args.min_total, args.min_speech, args.max_speech, args.max_tics, args.max_run))
    fails = []
    for r in rows:
        why = []
        if args.min_total is not None and r["totalHan"] < args.min_total:
            why.append(f"全文 {r['totalHan']} < {args.min_total}")
        if args.min_speech is not None and r["speechHan"] < args.min_speech:
            why.append(f"口播 {r['speechHan']} < {args.min_speech}")
        if args.max_speech is not None and r["speechHan"] > args.max_speech:
            why.append(f"口播 {r['speechHan']} > {args.max_speech}")
        if args.max_tics is not None and len(r["aiTics"]) > args.max_tics:
            why.append(f"AI 腔 {len(r['aiTics'])} 处")
        if args.max_run is not None and r["maxSameSpeakerRun"] > args.max_run:
            why.append(f"同一人连说 {r['maxSameSpeakerRun']} 行，中间没有动作或接话")
        # 占位写法不看阈值，任何时候都算没写完
        why += [f"用「{t}」代替正文，把这段戏写出来：{l}" for t, l in r["placeholders"]]
        if why:
            fails.append({"ep": r["ep"], "why": why})
    totals = [r["totalHan"] for r in rows]
    report = {"episodes": rows,
              "summary": {"count": len(rows), "totalHanMin": min(totals), "totalHanMax": max(totals),
                          "totalHanMedian": sorted(totals)[len(totals) // 2],
                          "placeholderEps": [r["ep"] for r in rows if r["placeholders"]]},
              "failed": fails}
    if gated or fails:
        report["passed"] = not fails
    else:
        report["note"] = "没给阈值，只统计；交付前用 --min-total 等参数把体量目标变成闸门"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if fails else 0


def cmd_dup(args):
    """字面查重：新稿里与原剧语料连续 k 个汉字相同的片段，逐条列出。只统计，不判过不过。"""
    with open(args.source, encoding="utf-8") as f:
        src = "".join(re.findall(r"[\u4e00-\u9fff]", f.read()))
    grams = {src[i:i + args.k] for i in range(len(src) - args.k + 1)}
    hits, covered, total = [], 0, 0
    with open(args.draft, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            if COMMENT.match(line):
                continue
            han = "".join(re.findall(r"[\u4e00-\u9fff]", line))
            total += len(han)
            mark = [False] * len(han)
            for i in range(len(han) - args.k + 1):
                g = han[i:i + args.k]
                if g in grams:
                    hits.append({"line": ln, "ngram": g})
                    for j in range(i, i + args.k):
                        mark[j] = True
            covered += sum(mark)
    print(json.dumps({"k": args.k, "hitCount": len(hits), "newHanChars": total,
                      "coveredRatio": round(covered / total, 4) if total else 0,
                      "hits": hits[:200], "note": "日常口语撞上可以留；原剧有辨识度的句子或成段逐句对上要改"},
                     ensure_ascii=False, indent=2))
    return 0


VISUAL_TERMS = ["画左", "画右", "画面", "镜头", "特写", "近景", "中景", "远景", "全景", "俯拍", "仰拍", "航拍",
                "推近", "拉远", "拉高", "摇镜", "机位", "景别", "分镜", "定格", "淡出", "淡入", "白化", "字幕"]
LOOK_TERMS = ["身穿", "穿着", "一身", "外形", "外貌", "长相", "相貌", "发型", "发髻", "高挽", "发簪", "盘发", "妆容", "化妆",
              "旗袍", "西装", "西服", "衬衫", "领带", "马甲", "连衣裙", "长裙", "高跟鞋", "皮鞋", "布鞋", "眼镜", "耳坠",
              "项链", "手镯", "戒指", "白发", "银发", "黑发", "卷发", "长发", "短发", "浓眉", "瓜子脸", "面容", "清丽"]
GENERIC_SPEAKER = re.compile(r"^(.{0,6}[甲乙丙丁戊己]|.{0,6}[A-Za-z0-9]|路人|男子|女子|男人|女人|众人|某人)$")
STD_LINE = re.compile(r"^(#{1,2} |场\d|人物[:：]|△|<!--|---$)")


def cmd_rules(args):
    """客户制作规则：每场说话人数、单句汉字数；括注只在 --require-annotation 时判。"""
    with open(args.draft, encoding="utf-8") as f:
        lines = [l if not COMMENT.match(l) else "" for l in f.read().splitlines()]
    scene, speakers, over, long_, nop = None, {}, [], [], []
    visual, look, fmt, generic = [], [], [], {}
    in_eps = False
    for i, l in enumerate(lines, 1):
        st = l.strip()
        if EP_HEAD.match(l):
            in_eps = True
        desc = st.startswith("△") or st.startswith("人物") or not in_eps  # 动作行、人物行、集前的人物小传
        paren = "".join(re.findall(r"（[^）]*）", st))
        zone = st if desc else paren
        visual += [{"line": i, "term": t, "text": st[:40]} for t in VISUAL_TERMS if t in zone][:1]
        look += [{"line": i, "term": t, "text": st[:40]} for t in LOOK_TERMS if t in zone][:1]
        if in_eps and st and not STD_LINE.match(st) and not SPEECH.match(st):
            fmt.append({"line": i, "text": st[:40]})
        elif in_eps and re.search(r"\[原E|【钩子】", st):
            fmt.append({"line": i, "text": st[:40]})
        if l.startswith("场"):
            scene = l.split()[0]
            speakers[scene] = set()
            continue
        m = SPEECH.match(l)
        if not (m and scene):
            continue
        speakers[scene].add(m.group(1))
        if GENERIC_SPEAKER.match(m.group(1).strip()):
            generic.setdefault(m.group(1).strip(), i)
        han = len(re.findall(r"[\u4e00-\u9fff]", m.group(3)))
        if han > args.max_han:
            long_.append({"line": i, "speaker": m.group(1), "han": han})
        if not m.group(2):
            nop.append({"line": i, "text": l[:30]})
    over = [{"scene": k, "speakers": sorted(v)} for k, v in speakers.items() if len(v) > args.max_speakers]
    report = {"tooManySpeakers": over, "tooLong": long_, "noAnnotation": nop,
              "visual": visual, "appearance": look, "format": fmt,
              "genericNames": [{"name": k, "line": v} for k, v in generic.items()],
              "passed": not (over or long_ or (nop and args.require_annotation) or visual or look or fmt or generic)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


CAST_LINE = re.compile(r"^人物\s*[:：](.*)")
EXIT_ACT = re.compile(r"(离开|走出(?:门|屋|院|去)|出了(?:门|屋|院)|摔门而去|扬长而去|转身离开|转身出(?:门|去)|走远了|"
                      r"下山去了|挂(?:断|了)电话|跑出(?:门|去)|走了出去|退了出去|出门去了)")
ENTER_ACT = re.compile(r"(进来|进了|走进|回来|回到|推门|跑回|折回|又进|闯进|冲进|追进|跟进)")
OFFSCREEN = re.compile(r"画外|电话|话筒|喊声|远处|门外|窗外|录音|广播|信里")
IMPL_DECL = re.compile(r"^\s*[-*]?\s*(加人|离场|回归)\s*[:：]\s*([^\s—–\-:：（(]+)\s*(?:[—–\-:：（(]+\s*(.*?))?\s*[）)]?\s*$", re.M)


def _cast_names(spec):
    return {x for x in re.split(r"[\s、，,]+", spec) if x}


def _decls(impl_text):
    """实现表里的出场声明：加人/离场/回归，每条要写理由。"""
    out = []
    for m in IMPL_DECL.finditer(impl_text):
        out.append({"kind": m.group(1), "who": m.group(2), "why": (m.group(3) or "").strip()})
    return out


def presence_model(extract, sheet, impl_eps):
    """每集的新剧名册（原剧在场的人照选角表换名）和离场时间线（原剧离场 + 实现表声明）。"""
    mpath = os.path.join(extract, "manifest.json")
    manifest = load_sheet(mpath) if os.path.exists(mpath) else {"episodes": {}}
    cpath = os.path.join(extract, "cast.json")
    cast = load_sheet(cpath) if os.path.exists(cpath) else {}
    sheet_eps = {e["ep"]: e for e in sheet.get("episodes", [])}

    def new(name):
        return cast.get(name) or cast.get(PAREN_NAME.sub("", name).strip()) or ""

    roster, events = {}, {}
    for n in sorted(set(sheet_eps) | {int(k) for k in manifest["episodes"]}):
        src = manifest["episodes"].get(str(n), {})
        e = sheet_eps.get(n, {})
        names = set(src.get("speakers", [])) | set(src.get("mentioned", [])) | set(e.get("onScreen", []))
        for b in e.get("beats", []):
            names |= set(b.get("roles", []))
        roster[n] = {new(x) for x in names} - {""}
        for kind, key in (("离场", "exits"), ("回归", "returns")):
            for x in e.get(key, []):
                who = new(x.get("who", ""))
                if who:
                    events.setdefault(n, []).append({"kind": kind, "who": who, "why": x.get("why") or x.get("how") or "原剧",
                                                     "from": "原剧"})
    for n, body in impl_eps.items():
        for d in _decls(body):
            if d["kind"] != "加人":
                events.setdefault(n, []).append({**d, "from": "实现表"})
    return roster, events


def gone_before(events, upto):
    """第 upto 集开拍时谁处在离场状态：{人: (离场集, 原因)}。离场从下一集起生效，回归当集生效。"""
    gone = {}
    for n in sorted(k for k in events if k <= upto):
        for ev in events[n]:
            if ev["kind"] == "回归":
                gone.pop(ev["who"], None)
            elif n < upto:
                gone[ev["who"]] = (n, ev["why"])
    return gone


def scan_scenes(text):
    """场内：说话人不在本场人物表；离场后没写回来又开口。画外音、电话里的声音不算在场。"""
    problems, spoken = [], set()
    scene, cast, gone = None, set(), {}
    for l in text.splitlines():
        st = l.strip()
        if st.startswith("场") and re.match(r"场\d", st):
            scene, cast, gone = st.split()[0], set(), {}
            continue
        m = CAST_LINE.match(st)
        if m:
            cast = _cast_names(m.group(1))
            spoken |= cast
            continue
        if st.startswith("△"):
            for c in cast:
                for k in EXIT_ACT.finditer(st):
                    pre = st[:k.start()]
                    if c in pre[-10:] and not re.search(r"[，。；！？]", pre[pre.rfind(c):]):
                        gone[c] = st[:30]
                for k in ENTER_ACT.finditer(st):
                    if c in st[:k.start()][-10:]:
                        gone.pop(c, None)
            continue
        m = SPEECH.match(l)
        if not (m and scene):
            continue
        who = m.group(1).strip()
        spoken.add(who)
        if OFFSCREEN.search(m.group(2) or ""):
            continue
        if cast and who not in cast:
            problems.append(f"{scene} {who} 开口了，但不在本场「人物：」里：补进人物行，或改成画外音")
        if who in gone:
            problems.append(f"{scene} {who} 已经离场（{gone[who]}），后面又开口：先写他回来，或删掉这句")
    return problems, spoken


def cmd_presence(args):
    """出场逻辑闸门：场内在场一致；每集出场对得上原剧名册，名册外的人要在实现表写「加人：名字 — 理由」；
    离场的人回来要写「回归：名字 — 怎么回来的」。"""
    sheet = load_sheet(args.sheet)
    with open(args.draft, encoding="utf-8") as f:
        draft = split_episodes(f.read())
    impl = {}
    if args.impl:
        import glob
        # 前面批次的实现表里写过的离场/回归也要算，同目录的 impl-*.md 一起读
        for p in sorted(set(glob.glob(os.path.join(os.path.dirname(args.impl) or ".", "impl-*.md"))) | {args.impl}):
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    for n, body in split_episodes(f.read()).items():
                        impl[n] = impl.get(n, "") + "\n" + body
    roster, events = presence_model(args.extract, sheet, impl)
    problems = []
    for n in sorted(draft):
        scene_problems, here = scan_scenes(draft[n])
        problems += [f"第{n}集 {p}" for p in scene_problems]
        decls = _decls(impl.get(n, ""))
        added = {d["who"]: d["why"] for d in decls if d["kind"] == "加人"}
        problems += [f"第{n}集实现表「{d['kind']}：{d['who']}」没写理由" for d in decls if not d["why"]]
        if roster.get(n):
            for who in sorted(here - roster[n] - set(added)):
                problems.append(f"第{n}集 {who} 出场了，原剧这集没有对应的人：要留就在实现表写「加人：{who} — 理由」，否则删掉")
        for who, (since, why) in sorted(gone_before(events, n).items()):
            if who in here:
                problems.append(f"第{n}集 {who} 第{since}集已离场（{why}），这集又出场：实现表写「回归：{who} — 怎么回来的」，或删掉")
    report = {"problems": problems, "passed": not problems,
              "rosterMissing": not any(roster.values()),
              "note": "名册来自 manifest 的说话人和剧情提到的人、节拍的 roles/onScreen，经 cast.json 换成新剧名"}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if not problems else 2


GENERIC_ROLES = set("""中年妇女 二叔 二舅妈 兄长 劝架妇女 受伤青年 同伙 同伴青年 后妈 继母 商人 壮汉 外婆 外公 大叔 大夫
大婶 大舅妈 女店员 女村民 女职员 妹妹 弟弟 哥哥 姐姐 师傅 干部 年轻女子 年长女子 店主 店员 少年 少女 支书 村民 村长
母亲 父亲 老人 老者 青年 经理 门卫 舅舅 舅妈 姥姥 大舅 二舅 表哥 表弟 儿媳 线人 领袖 奶奶 爷爷""".split())


def cmd_build(args):
    """把逐集提取的 beats/ep-NNN.json 合成全季节拍表和指纹表，过滤泛称和过短的词。"""
    import glob
    import os
    base = load_sheet(args.base)
    eps = {e["ep"]: e for e in base.get("episodes", [])}
    fps = list(base.get("fingerprints", []))
    names = {r["sourceName"] for r in base.get("roles", []) if r.get("sourceName")}
    handwritten = sorted(eps)
    eps = {}  # 节拍只认逐集提取文件；beat-sheet.json 里手写的 episodes 不进全季表
    sources = []
    for p in sorted(glob.glob(os.path.join(args.extract, "beats", "ep-*.json"))):
        j = load_sheet(p)
        n = j["ep"]
        with open(p, "rb") as f:
            sources.append({"file": os.path.basename(p), "sha1": hashlib.sha1(f.read()).hexdigest()[:12]})
        eps[n] = {"ep": n, "beats": j["beats"], "hook": j.get("hook", ""), "climax": bool(j.get("climax")),
                  "onScreen": j.get("onScreen", []), "exits": j.get("exits", []), "returns": j.get("returns", [])}
        render_dialogue_map(args.extract, n, j)
        terms = [t for t in j.get("fingerprints", []) if isinstance(t, str) and 4 <= len(t) <= 30]
        fps.append({"id": f"F-E{n}", "kind": "其他", "episodes": [n], "terms": terms})
        for c in j.get("newCharacters", []):
            s = (c.get("sourceName") or "").strip()
            if 2 <= len(s) <= 4 and s not in GENERIC_ROLES and re.fullmatch(r"[\u4e00-\u9fff]+", s):
                names.add(s)
    if not eps:
        print(json.dumps({"error": f"{args.extract}/beats/ 下没有 ep-*.json，先逐集提取"}, ensure_ascii=False))
        return 1
    mpath = os.path.join(args.extract, "manifest.json")
    manifest = load_sheet(mpath) if os.path.exists(mpath) else {}
    names |= set(manifest.get("names", []))
    fps.append({"id": "F-NAMES", "kind": "人名", "terms": sorted(names)})
    total = manifest.get("total") or base.get("totalEpisodes") or max(eps)
    gaps = manifest.get("gaps", base.get("gaps", []))
    out = {"source": base.get("source"), "totalEpisodes": total, "roles": base.get("roles", []),
           "episodes": [eps[k] for k in sorted(eps)], "gaps": gaps, "fingerprints": fps,
           "builtFrom": sources}
    with open(args.out_beats, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open(args.out_fp, "w", encoding="utf-8") as f:
        json.dump({"fingerprints": fps, "roles": [], "episodes": []}, f, ensure_ascii=False, indent=1)
    present = set(manifest.get("present", []))
    print(json.dumps({"episodes": len(eps), "beats": sum(len(e["beats"]) for e in eps.values()),
                      "names": len(names), "ignoredHandwritten": handwritten,
                      "notExtractedYet": sorted(present - set(eps)) if present else None},
                     ensure_ascii=False))
    return 0


TIMECODE = re.compile(r"(\d{1,2}):(\d{2})(?:\.(\d+))?")
TURN = re.compile(r"Speaker:\s*(.+?)\s*\n\s*State:\s*(.*?)\s*\n\s*Content:\s*(.+)")
HOOK_SRC = re.compile(r"\*\*结尾钩子[:：]\*\*\s*(.+)")
PAREN_NAME = re.compile(r"[（(][^）)]*[）)]")


SURNAMES = set("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎"
               "鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
               "和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭"
               "梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯管卢莫房裘缪解应宗丁宣邓郁单杭洪包诸左石崔吉龚程邢裴陆荣"
               "翁荀羊惠甄曲封储靳段富巫乌焦巴弓牧山谷车侯全班仰秋仲伊宫宁仇栾暴甘厉戎祖武符刘景詹龙叶幸司黎薄印"
               "宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥苍双闻党翟谭贡劳姬申扶冉宰雍桑桂濮牛寿通边燕冀温庄晏柴瞿阎"
               "慕连茹习艾鱼容向古易慎戈廖庾终居衡步都耿满弘匡国文寇广禄阙东欧沃利蔚越隆师巩聂晁勾敖融冷辛阚那简"
               "饶曾沙养鞠须丰巢关蒯相查后荆红游竺权盖益桓公")
TITLE_SUFFIX = ("律师", "医生", "大夫", "老师", "经理", "秘书", "管家", "助理", "总", "董", "局", "警官", "队长", "老板",
                "老爷", "夫人", "太太", "小姐", "先生", "师傅", "妈", "嫂", "叔", "伯", "姐", "哥", "婶", "姨", "爷", "奶",
                "父", "母", "少", "某", "女", "男", "人")


def is_proper_name(nm):
    """只收真名：常见姓开头、2-3 个汉字、不以称谓结尾。泛称和语气词收进来会让指纹扫描满屏误报。"""
    return (bool(re.fullmatch(r"[\u4e00-\u9fff]{2,3}", nm)) and nm[0] in SURNAMES
            and not nm.endswith(TITLE_SUFFIX) and nm not in GENERIC_ROLES)


def _find_episode_list(obj):
    """在任意嵌套的 JSON 里找逐集列表：元素是带 rawMd 的 dict。"""
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj) and any("rawMd" in x for x in obj):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            r = _find_episode_list(v)
            if r is not None:
                return r
    return None


def _find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find_key(v, key)
            if r is not None:
                return r
    return None


def parse_episode(raw, outline):
    turns = []
    for m in TURN.finditer(raw):
        content = m.group(3).strip().strip("“”\"「」")
        speaker = m.group(1).strip()
        turns.append({"speaker": speaker, "state": m.group(2).strip(), "line": content})
    secs = [int(a) * 60 + int(b) for a, b, _ in TIMECODE.findall(raw)]
    hook = HOOK_SRC.search(outline or "")
    return {"turns": turns, "durationSec": max(secs) if secs else None,
            "speechHan": sum(len(HAN.findall(t["line"])) for t in turns),
            "hookSrc": hook.group(1).strip() if hook else ""}


def source_turns(extract, n):
    path = os.path.join(extract, "source", f"ep-{n:03d}.txt")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        part = f.read().split("## 台词（按顺序）")[-1].split("## Storyline")[0]
    out = []
    for l in part.splitlines():
        parts = l.strip().split("｜", 2)
        if len(parts) == 3:
            out.append({"speaker": parts[0], "state": parts[1], "line": parts[2]})
    return out


def render_dialogue_map(extract, n, j, cast=None):
    """台词结构图由脚本从节拍的 turns 认领自动生成：说话顺序是确定的，模型只填每拍的作用和手法。"""
    turns = source_turns(extract, n)
    cast = cast or {}
    rows = [f"## 第{n}集（{j.get('durationSec') or '?'} 秒，原剧 {len(turns)} 轮台词）", "",
            "| 节拍 | 轮次 | 说话顺序 | 作用 / 手法 |", "|---|---|---|---|"]
    for b in j.get("beats", []):
        t = b.get("turns")
        seq = "（纯画面）"
        k = 0
        if t:
            seg = turns[t[0] - 1:t[1]]
            k = len(seg)
            seq = " → ".join(f"{cast.get(x['speaker'], x['speaker'])}（{x['state'].split('，')[0]}）" for x in seg)
        rows.append(f"| {b['id'].split('-')[-1]} | {k} | {seq} | {b.get('craft', '')} |")
    os.makedirs(os.path.join(extract, "dialogue"), exist_ok=True)
    with open(os.path.join(extract, "dialogue", f"ep-{n:03d}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")


def cmd_source(args):
    """把拉片模板（整份 JSON 或逐集 evidence 目录）落成逐集原文和清单。确定性的活由脚本做，模型不必通读几十万字。"""
    import glob
    items, total = [], None
    if os.path.isdir(args.input):
        for p in sorted(glob.glob(os.path.join(args.input, "*.json"))):
            j = load_sheet(p)
            total = total or _find_key(j, "episodesTotal") or _find_key(j, "totalEpisodes")
            window = _find_episode_list(j)
            if window:  # 分集窗口：一个文件装多集
                items.extend(window)
                continue
            ep = _find_key(j, "episodeIndex") or int(re.findall(r"\d+", os.path.basename(p))[-1])
            items.append({"episodeIndex": ep, "rawMd": _find_key(j, "rawMd") or "",
                          "outlineMd": _find_key(j, "episodeOutlineMd") or _find_key(j, "outlineMd") or ""})
    else:
        j = load_sheet(args.input)
        items = _find_episode_list(j) or []
        total = _find_key(j, "episodesTotal") or _find_key(j, "totalEpisodes")
    if not items:
        print(json.dumps({"error": "没找到逐集数据（带 rawMd 的列表）"}, ensure_ascii=False))
        return 1
    os.makedirs(os.path.join(args.out, "source"), exist_ok=True)
    eps, names, corpus, texts = {}, set(), [], {}
    for it in items:
        n = int(it["episodeIndex"])
        raw, outline = it.get("rawMd") or "", it.get("outlineMd") or ""
        if not raw.strip() and not outline.strip():
            continue
        info = parse_episode(raw, outline)
        for t in info["turns"]:
            sp = t["speaker"]
            for nm in [PAREN_NAME.sub("", sp).strip()] + re.findall(r"[（(]([\u4e00-\u9fff]{2,4})[）)]", sp):
                if is_proper_name(nm):
                    names.add(nm)
        body = [outline.strip(), "", "## 台词（按顺序）"]
        body += [f"{t['speaker']}｜{t['state']}｜{t['line']}" for t in info["turns"]]  # 说话人本身可能带括号，用｜分隔
        story = raw.split("## Visible Text")[0]
        body += ["", "## Storyline", story.strip()]
        with open(os.path.join(args.out, "source", f"ep-{n:03d}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(body))
        corpus.append("\n".join(t["line"] for t in info["turns"]) + "\n" + story)
        texts[n] = outline + "\n" + story
        eps[n] = {"durationSec": info["durationSec"], "turns": len(info["turns"]),
                  "speechHan": info["speechHan"], "hookSrc": info["hookSrc"],
                  "speakers": sorted({t["speaker"] for t in info["turns"]})}
    for n, text in texts.items():  # 剧情里提到、但这集不说话的人，也算在场
        eps[n]["mentioned"] = sorted(nm for nm in names if nm in text)
    total = total or max(eps)
    manifest = {"total": total, "present": sorted(eps), "gaps": [i for i in range(1, total + 1) if i not in eps],
                "names": sorted(names), "episodes": {str(k): eps[k] for k in sorted(eps)}}
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "corpus.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(corpus))
    noturns = [k for k in eps if not eps[k]["turns"]]
    nohook = [k for k in eps if not eps[k]["hookSrc"]]
    print(json.dumps({"warning": f"原剧 {total} 集，超过 70 集上限：裂变时要合并压缩，或换一部" if total > 70 else None,
                      "total": total, "present": len(eps), "gaps": manifest["gaps"], "names": manifest["names"],
                      "noTranscript": noturns, "noHook": nohook,
                      "files": ["manifest.json", "corpus.txt", "source/ep-NNN.txt"]}, ensure_ascii=False, indent=2))
    return 0


IMPL_HOOK_SRC = re.compile(r"原剧钩子[ \t]*[:：][ \t]*(\S.*)")  # 不跨行：空着的「新剧钩子：」不能吃到下一行
IMPL_HOOK_NEW = re.compile(r"新剧钩子[ \t]*[:：][ \t]*(\S.*)")


def _norm(t):
    return "".join(HAN.findall(t))


def cmd_gate(args):
    """写正文前后的闸门：前置产物齐不齐、体量够不够原剧、钩子有没有照原剧对位。过不了就不交付。"""
    manifest = load_sheet(os.path.join(args.extract, "manifest.json"))
    sheet = load_sheet(args.sheet)
    with open(args.draft, encoding="utf-8") as f:
        draft = split_episodes(f.read())
    impl = {}
    if args.impl:
        with open(args.impl, encoding="utf-8") as f:
            impl = split_episodes(f.read())
    problems, rows, pair = [], [], []
    if not sheet.get("builtFrom"):
        problems.append("节拍表不是 build 合成的（缺 builtFrom）。手写的节拍表不算数，先逐集提取再 build")
    sheet_eps = {e["ep"]: e for e in sheet.get("episodes", [])}
    for n in sorted(draft):
        src = manifest["episodes"].get(str(n))
        if not src:
            problems.append(f"第{n}集：原剧这一集没有数据（缺集），不能按对位写")
            continue
        need = [f"source/ep-{n:03d}.txt", f"beats/ep-{n:03d}.json", f"dialogue/ep-{n:03d}.md"]
        lacking = [x for x in need if not os.path.exists(os.path.join(args.extract, x))
                   or os.path.getsize(os.path.join(args.extract, x)) < 50]
        if lacking:
            problems.append(f"第{n}集缺前置产物：{lacking}")
        nb = len(sheet_eps.get(n, {}).get("beats", []))
        dpath = os.path.join(args.extract, f"dialogue/ep-{n:03d}.md")
        if os.path.exists(dpath):
            with open(dpath, encoding="utf-8") as f:
                drows = [l for l in f if re.match(r"\|\s*B\d+", l)]
            if len(drows) < nb:
                problems.append(f"第{n}集：台词结构图只有 {len(drows)} 拍，节拍表有 {nb} 拍")
        st = episode_stats(n, draft[n])
        line_ratio = st["speechLines"] / src["turns"] if src["turns"] else None
        han_ratio = st["speechHan"] / src["speechHan"] if src["speechHan"] else None
        if line_ratio is not None and line_ratio < args.min_line_ratio:
            problems.append(f"第{n}集：台词 {st['speechLines']} 行，原剧 {src['turns']} 轮，"
                            f"不到 {args.min_line_ratio:.0%}，多半丢了拍")
        if han_ratio is not None and han_ratio < args.min_speech_ratio:
            problems.append(f"第{n}集：口播 {st['speechHan']} 字，原剧 {src['speechHan']} 字，"
                            f"不到 {args.min_speech_ratio:.0%}")
        if han_ratio is not None and han_ratio > args.max_speech_ratio:
            problems.append(f"第{n}集：口播 {st['speechHan']} 字，原剧 {src['speechHan']} 字，"
                            f"超过 {args.max_speech_ratio:.0%}，时长会比原剧长出一截，删短")
        hook_ok = None
        if impl:
            body = impl.get(n, "")
            hs, hn = IMPL_HOOK_SRC.search(body), IMPL_HOOK_NEW.search(body)
            if not hs or not hn:
                problems.append(f"第{n}集实现表缺「原剧钩子：」或「新剧钩子：」行")
            elif src["hookSrc"] and _norm(hs.group(1))[:12] not in _norm(src["hookSrc"]):
                problems.append(f"第{n}集实现表里的原剧钩子和原剧不符，照 manifest 抄：{src['hookSrc'][:40]}")
            else:
                hook_ok = True
        rows.append({"ep": n, "srcTurns": src["turns"], "newLines": st["speechLines"],
                     "srcSpeechHan": src["speechHan"], "newSpeechHan": st["speechHan"],
                     "lineRatio": round(line_ratio, 2) if line_ratio else None,
                     "speechRatio": round(han_ratio, 2) if han_ratio else None, "hookRecorded": hook_ok})
        if args.pair_out:
            with open(os.path.join(args.extract, f"source/ep-{n:03d}.txt"), encoding="utf-8") as f:
                src_lines = [l.rstrip() for l in f.read().split("## 台词（按顺序）")[-1].split("## Storyline")[0].splitlines() if l.strip()]
            new_lines = [l.rstrip() for l in draft[n].splitlines() if SPEECH.match(l)]
            hn = IMPL_HOOK_NEW.search(impl.get(n, "")) if impl else None
            pair.append(f"## 第{n}集\n\n原剧钩子：{src['hookSrc']}\n新剧钩子：{hn.group(1) if hn else '（实现表没写）'}\n")
            pair.append("| # | 原剧（说话人 · 语气 · 台词） | 新剧 |\n|---|---|---|")
            for i in range(max(len(src_lines), len(new_lines))):
                a = src_lines[i] if i < len(src_lines) else ""
                b = new_lines[i] if i < len(new_lines) else ""
                pair.append(f"| {i + 1} | {a.replace('|', '/')} | {b.replace('|', '/')} |")
            pair.append("")
    if args.pair_out:
        with open(args.pair_out, "w", encoding="utf-8") as f:
            f.write("# 原剧 / 新剧 逐句对照（人审用：看每一轮的作用和人味对不对得上，不看字面）\n\n" + "\n".join(pair))
    report = {"episodes": rows, "problems": problems, "passed": not problems,
              "pairOut": args.pair_out,
              "note": "gate 只管结构和数量；钩子的意思像不像、台词有没有人味，要人看 pairOut 对照表"}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not problems else 2



def parse_range(r):
    a, _, b = r.partition("-")
    return list(range(int(a), int(b or a) + 1))


def cmd_scaffold(args):
    """给一段集数生成预填好的提取骨架：原剧钩子、时长、台词轮数、按轮次切好的节拍槽。模型只填空，不从零写。"""
    manifest = load_sheet(os.path.join(args.extract, "manifest.json"))
    os.makedirs(os.path.join(args.extract, "beats"), exist_ok=True)
    made, skipped = [], []
    for n in parse_range(args.range):
        src = manifest["episodes"].get(str(n))
        if not src:
            skipped.append(n)
            continue
        path = os.path.join(args.extract, "beats", f"ep-{n:03d}.json")
        if os.path.exists(path) and not args.force:
            skipped.append(n)
            continue
        k = max(4, min(8, round(src["turns"] / 3.5) or 4))
        cuts = [round(i * src["turns"] / k) for i in range(k + 1)]
        beats = []
        for i in range(k):
            a, z = cuts[i] + 1, cuts[i + 1]
            beats.append({"id": f"E{n}-B{i + 1}", "turns": [a, z] if z >= a else None,
                          "function": "", "roles": [], "emotion": 0, "payoff": "无",
                          "craft": "本拍每一轮起什么作用 + 手法，例：长辈哭求 → 铺主开价（对仗规矩句）"})
        skel = {"ep": n, "durationSec": src["durationSec"], "hookSrc": src["hookSrc"],
                "_说明": f"读 source/ep-{n:03d}.txt 整集。turns 是预切的轮次范围，按剧情改成真实的拍界（全部轮次都要认领、按顺序）；"
                         "function 写抽象功能，不带原剧专名；hook 对着 hookSrc 抽象。",
                "beats": beats, "hook": "", "climax": False, "powerUse": None,
                "moneyAndAssets": "", "stateAfter": "", "newCharacters": [], "fingerprints": []}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(skel, f, ensure_ascii=False, indent=1)
        made.append(n)
    print(json.dumps({"made": made, "skipped": skipped,
                      "next": f"逐集填 {args.extract}/beats/ep-NNN.json，填完跑 build 和 sheet --range {args.range}"},
                     ensure_ascii=False))
    return 0


def cmd_cast(args):
    """列出原剧这一段所有说话人，生成 原名→新剧名 的选角表骨架；brief 用它把台词结构图换成新剧人名。"""
    manifest = load_sheet(os.path.join(args.extract, "manifest.json"))
    path = os.path.join(args.extract, "cast.json")
    cast = load_sheet(path) if os.path.exists(path) else {}
    for n in parse_range(args.range):
        for sp in manifest["episodes"].get(str(n), {}).get("speakers", []):
            cast.setdefault(sp, "")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cast, f, ensure_ascii=False, indent=1)
    empty = [k for k, v in cast.items() if not v]
    generic = sorted({v for v in cast.values() if v and GENERIC_SPEAKER.match(v)})
    print(json.dumps({"file": path, "unfilled": empty, "genericNames": generic,
                      "note": "按 season-map 填新剧名；同一人不同写法（年轻时/年老时、错别字）填同一个名字"}, ensure_ascii=False))
    return 0


CHARS_PER_SEC = 3.0  # 口播字数 / 成片秒数；含动作和停顿，90 秒约 270 字


def cmd_brief(args):
    """为一批生成写手任务单 + 正文骨架：每拍的原剧轮次换成新剧人名排好，钩子和体量写死。写手照着填，不用自己找。"""
    manifest = load_sheet(os.path.join(args.extract, "manifest.json"))
    sheet = load_sheet(args.sheet)
    cast = load_sheet(os.path.join(args.extract, "cast.json"))
    eps = {e["ep"]: e for e in sheet.get("episodes", [])}
    rng = parse_range(args.range)
    fp = sorted(fingerprint_terms(sheet, manifest))
    head = ["每一拍都按下表写：轮次数和说话顺序对上，每句话自己写，不翻译原句。写完立刻跑 `check`，过了再要下一集。", "",
            "**一次只写这一集，只读这一份任务包。** 圣经里本集要用的人物、地图里本集的分段、样集、写作规则都附在后面，"
            "不用再去读 bible.md、season-map.md、references/，也不回头读前面几集的正文，上一集的结尾状态已经写在本单里。"
            "整集写完，不许用「略」「同上」「此处省略」「以此类推」代替任何一段戏，`check` 会拦。", "",
            f"**不许出现的词**：{'、'.join(fp[:60])}", "",
            "**出场规则**：每集只用「本集出场」里的人。要多加一个人，在实现表这一集写「加人：名字 — 理由」；"
            "有人离开（进城、入狱、搬走、去世），写「离场：名字 — 原因」；离场的人再出现，先写「回归：名字 — 怎么回来的」。"
            "开口的人必须在本场「人物：」行里；离场后没写回来不能再开口；电话、画外音在括注里标明。", ""]
    import glob
    prior = {}
    for p in sorted(glob.glob(os.path.join(args.out, "impl-*.md"))):
        with open(p, encoding="utf-8") as f:
            for k, body in split_episodes(f.read()).items():
                prior[k] = prior.get(k, "") + "\n" + body
    roster, events = presence_model(args.extract, sheet, prior)
    last_ep = max(int(k) for k in manifest["episodes"])
    os.makedirs(args.out, exist_ok=True)
    files, skipped = [], []
    for n in rng:
        src = manifest["episodes"].get(str(n))
        if not src or n not in eps:
            skipped.append(n)
            continue
        j = load_sheet(os.path.join(args.extract, "beats", f"ep-{n:03d}.json"))
        turns = source_turns(args.extract, n)
        lo, hi = round(src["turns"] * 0.8), round(src["turns"] * 1.4)
        # 时长默认照原剧这一集；只有用户/制作方给了时长上限（--sec）才往下压
        cap = round(args.sec * CHARS_PER_SEC) if args.sec else None
        s_lo, s_hi = round(src["speechHan"] * 0.8), round(src["speechHan"] * 1.3)
        if cap:
            s_lo, s_hi = min(s_lo, round(cap * 0.8)), min(s_hi, cap)
        tier, why = model_tier(n, sheet, eps, last_ep)
        prev = EXIT_STATE.search(prior.get(n - 1, ""))
        brief = [f"# 写作任务单 第{n}集", "", *head,
                  f"- **模型**：{TIER_TEXT[tier]}" + (f"（{'、'.join(why)}）" if why else ""),
                  f"- 原剧时长 {src['durationSec']} 秒，{src['turns']} 轮台词、口播 {src['speechHan']} 字。",
                  f"- **体量**：台词 {lo}-{hi} 行，口播 {s_lo}-{s_hi} 字，时长照原剧（约 {src['durationSec']} 秒）。"
                  + (f"用户定了单集 {args.sec} 秒上限，原剧这集更长：在本集节拍内压缩，少一轮、句子更短，不删拍。"
                     if cap and src["speechHan"] > cap else ""),
                  "- 每一轮括号里是原剧这句的字数，新句子照这个长度写，单句不超过 20 字。不写外貌、不写画面，龙套用唯一称呼。",
                  f"- **原剧钩子**：{src['hookSrc']}",
                  f"- **上一集结尾状态**：{prev.group(1).strip() if prev else '（第一集）' if n == min(int(k) for k in manifest['episodes']) else f'（第{n - 1}集实现表还没写「出口状态」：先补上它，再写这一集）'}",
                  f"- **本集出场**（照原剧映射）：{'、'.join(sorted(roster.get(n, set()))) or '（选角表没填，先跑 cast 填好）'}",
                  *([f"- **已离场，不能出场**：" + "；".join(f"{w}（第{s}集起，{y}）" for w, (s, y) in sorted(gone_before(events, n).items()))]
                    if gone_before(events, n) else []),
                  f"- **只写本集的拍**，下一集的戏不提前。",
                  f"- **写进**：正文 `{os.path.join(args.out, f'draft-{n:03d}.md')}`（骨架已在，照下表每拍一个注释槽填），"
                  f"实现表 `{os.path.join(args.out, f'impl-{n:03d}.md')}`（补新剧钩子和出口状态）。",
                  f"- **写完跑**：`python3 {os.path.abspath(__file__)} check {os.path.join(args.out, f'draft-{n:03d}.md')} "
                  f"--extract {args.extract} --sheet {args.sheet} --impl {os.path.join(args.out, f'impl-{n:03d}.md')}"
                  + (f" --min-total {args.min_total}" if args.min_total else "") + (f" --sec {args.sec}" if args.sec else "") + "`", "",
                  "| 拍 | 功能 | 轮次 | 说话顺序（新剧人名） | 作用 / 手法 |", "|---|---|---|---|---|"]
        skel = [f"# 第{cn_num(n)}集\n"]
        impl = [f"## 第{n}集", "对标节拍：" + ", ".join(b["id"] for b in j["beats"]),
                f"原剧钩子：{src['hookSrc']}", "新剧钩子：", "- 出口状态：", ""]
        for b in j["beats"]:
            t = b.get("turns")
            seg = turns[t[0] - 1:t[1]] if t else []
            def turn(x):
                k = len(HAN.findall(x["line"]))
                split = f"→拆{-(-k // 18)}行" if k > 20 else ""
                return f"{cast.get(x['speaker']) or x['speaker']}（{x['state'].split('，')[0].split('、')[0]}，{k}字{split}）"
            seq = " → ".join(turn(x) for x in seg) or "（无台词）"
            brief.append(f"| {b['id']} | {b['function']} | {len(seg)} | {seq} | {b.get('craft', '')} |")
            skel.append(f"<!-- {b['id']}｜{b['function']}｜{len(seg)} 轮：{seq} -->\n")
        skel.append(f"<!-- 钩子｜{j.get('hook', '')} -->\n")  # 用抽象钩子，原剧钩子带人名，留在任务单里
        # 一集一套文件：一次回复只写一集，长批次写到后面才不会缩水、写“略”
        paths = {k: os.path.join(args.out, f"{k}-{n:03d}.md") for k in ("brief", "draft", "impl")}
        brief += packet_extras(args.out, n, roster.get(n, set()))
        with open(paths["brief"], "w", encoding="utf-8") as f:
            f.write("\n".join(brief) + "\n")
        for k, body in (("draft", skel), ("impl", impl)):
            if os.path.exists(paths[k]) and not args.force:
                continue
            with open(paths[k], "w", encoding="utf-8") as f:
                f.write("\n".join(body))
        files.append({"ep": n, "model": tier, **paths})
    print(json.dumps({"files": files, "skipped": skipped,
                      **({"note": "原剧缺集或未提取，跳过了，告诉用户"} if skipped else {}),
                      "missingCast": sorted(k for k, v in cast.items() if not v)}, ensure_ascii=False))
    return 0


SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RANGE_IN_TEXT = re.compile(r"(\d+)\s*[-–~～至到]\s*(\d+)\s*集")


def _blocks(text):
    return [b for b in re.split(r"\n\s*\n", text) if b.strip()]


def _sections(text):
    """按 ##/###/#### 标题切小节；没有小节标题就按空行切段。"""
    secs = [s for s in re.split(r"(?m)^(?=#{2,4} )", text) if s.strip()]
    return secs if len(secs) > 1 else _blocks(text)


VOICE_SAMPLE = re.compile(r"示例台词|台词示例|口头禅")


def voiceless_leads(P, m, window, cast):
    """主要人物（在这一段一半以上的集里开口的）圣经里有没有写示例台词。没有示例，轻模型写出来人人一个腔。"""
    from collections import Counter
    c = Counter(cast.get(sp) for n in window for sp in m["episodes"][str(n)]["speakers"] if cast.get(sp))
    leads = [x for x, k in c.items() if k >= max(2, len(window) / 2)]
    secs = _sections(_read(os.path.join(P, "bible.md")))
    return [x for x in leads if not any(x in s and VOICE_SAMPLE.search(s) for s in secs)]


def _read(path):
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def packet_extras(out, n, names, cap=4000):
    """任务包附录：写一集要用的东西全附在一份文件里，写手读一次就开写。每多读一个文件就多一轮，每轮都要重读整个上下文。"""
    P = os.path.dirname(os.path.abspath(out))
    parts = ["", "---", "", "# 附录（写这一集要用的全在这里）", ""]
    bible = _read(os.path.join(P, "bible.md"))
    if bible:
        # 按小节摘：一个人的说话特点和示例台词常常不和名字在同一段，按空行切会把示例台词切丢
        secs = _sections(bible)
        keep = bible if len(bible) <= cap else "\n\n".join(s for s in secs if any(x in s for x in names))[:cap]
        parts += ["## 圣经：本集出场的人" + ("" if len(bible) <= cap else "（只摘了本集出场的人，别的要用再读 bible.md）"),
                  "", "每个人照自己的「说话」和「示例台词」写，盖住名字也要听得出是谁在说。", "", keep or bible[:cap], ""]
    smap = _read(os.path.join(P, "season-map.md"))
    if smap:
        if len(smap) <= cap:
            keep = smap
        else:
            secs = re.split(r"(?m)^(?=## )", smap)
            head = secs[0] + (secs[1] if len(secs) > 1 else "")  # 标题 + 第一节全季对照表：同一元素全季一种换法，每集都要守
            seg = [b for b in _blocks(smap) if any(int(a) <= n <= int(z) for a, z in RANGE_IN_TEXT.findall(b))]
            keep = (head[:cap] + "\n\n" + "\n\n".join(seg)[:cap]).strip()
        parts += ["## 全季地图：对照表和本集所在分段", "", keep, ""]
    if os.path.exists(os.path.join(P, "approved-sample.txt")):
        import glob
        drafts = sorted(p for p in glob.glob(os.path.join(out, "draft-*.md")) if not p.endswith(f"draft-{n:03d}.md"))
        if drafts:
            sample = COMMENT.sub("", _read(drafts[0])).strip()
            parts += ["## 定稿样集（口味基准：台词长短、口音、括注写法、△ 密度照它）", "", sample[:2500], ""]
    for ref, title in (("script-format.md", "正文格式"), ("anti-ai.md", "去 AI 味"), ("production-rules.md", "制作规则")):
        body = _read(os.path.join(SKILL_DIR, "references", ref))
        if body:
            parts += [f"## 规则：{title}", "", re.sub(r"(?m)^#", "###", body).strip(), ""]
    return parts


EXIT_STATE = re.compile(r"出口状态\s*[:：]\s*(\S.*)")
TIER_TEXT = {"main": "主力模型（会话顶档）", "light": "轻量模型即可（照骨架填空）"}


def model_tier(n, sheet, eps, last_ep, attempts=0):
    """哪些集值得用主力模型：定口味的前 10 集、★小高潮、总弹簧、大结局，以及轻模型改了两版还没过的集。其余照骨架填空，轻模型够用。"""
    why = []
    if n <= 10:
        why.append("前 10 集，客户最先看")
    if eps.get(n, {}).get("climax"):
        why.append("★小高潮集")
    if (sheet.get("mainSpring") or {}).get("episode") == n:
        why.append("总弹簧集")
    if n == last_ep:
        why.append("大结局")
    if attempts >= 2:
        why.append(f"改了 {attempts} 版还没过，换主力模型重写")
    return ("main" if why else "light"), why


def cn_num(n):
    d = "零一二三四五六七八九"
    if n < 10:
        return d[n]
    if n < 100:
        t, o = divmod(n, 10)
        return (d[t] if t > 1 else "") + "十" + (d[o] if o else "")
    h, r = divmod(n, 100)
    return d[h] + "百" + ("" if not r else ("零" + d[r] if r < 10 else cn_num(r) if r >= 20 else "一" + cn_num(r)))


def _run(fn, **kw):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(argparse.Namespace(**kw))
    try:
        return code, json.loads(buf.getvalue())
    except ValueError:
        return code, {"raw": buf.getvalue()}


def cmd_check(args):
    """写完一集马上跑的快检：一次跑完 gate/voice/rules/fingerprint/dup，只打印要改的地方，省读输出的 token。"""
    ex, sh = args.extract, args.sheet
    out = []
    _, g = _run(cmd_gate, draft=args.draft, extract=ex, sheet=sh, impl=args.impl, pair_out=None,
                min_line_ratio=0.7, min_speech_ratio=0.6, max_speech_ratio=1.3)
    out += g.get("problems", [])
    _, v = _run(cmd_voice, draft=args.draft, min_total=args.min_total, min_speech=None,
                max_speech=round(args.sec * CHARS_PER_SEC * 1.1) if args.sec else None, max_tics=0, max_run=3)
    out += [f"第{x['ep']}集：{'；'.join(x['why'])}" for x in v.get("failed", [])]
    out += [f"AI 腔「{t}」：{l}" for r in v.get("episodes", []) for t, l in r.get("aiTics", [])]
    _, r = _run(cmd_rules, draft=args.draft, max_speakers=4, max_han=20, require_annotation=False)
    out += [f"{x['scene']} 说话人 {len(x['speakers'])} 个：{'、'.join(x['speakers'])}" for x in r.get("tooManySpeakers", [])]
    out += [f"第 {x['line']} 行 {x['speaker']} 台词 {x['han']} 字，拆成两行或删短" for x in r.get("tooLong", [])]
    out += [f"第 {x['line']} 行写了画面「{x['term']}」，删掉：{x['text']}" for x in r.get("visual", [])]
    out += [f"第 {x['line']} 行写了外貌「{x['term']}」，删掉（形象以资产为准）：{x['text']}" for x in r.get("appearance", [])]
    out += [f"第 {x['line']} 行不是标准剧本行：{x['text']}" for x in r.get("format", [])]
    out += [f"龙套「{x['name']}」（第 {x['line']} 行）换成全季唯一的固定称呼" for x in r.get("genericNames", [])]
    _, pr = _run(cmd_presence, draft=args.draft, extract=ex, sheet=sh, impl=args.impl)
    out += pr.get("problems", [])
    _, fpr = _run(cmd_fingerprint, sheet=sh, draft=args.draft, ignore=None,
                  manifest=os.path.join(ex, "manifest.json"))
    out += [f"指纹「{h['term']}」第{h['ep']}集：{h['context']}" for h in fpr.get("hits", [])]
    _, d = _run(cmd_dup, draft=args.draft, source=os.path.join(ex, "corpus.txt"), k=8)
    out += [f"和原剧连续 8 字相同（第 {h['line']} 行）：{h['ngram']}" for h in d.get("hits", [])]
    with open(args.draft, encoding="utf-8") as f:
        text = f.read()
    empty = re.findall(r"<!-- (E\d+-B\d+)[^\n]*-->\s*\n\s*(?=<!--)", text)
    out += [f"{b} 还没写" for b in empty]
    # 套路反应：本集用了两次以上，或者前 10 集里已经用过（看同目录的其他集）
    others = season_stock(os.path.dirname(os.path.abspath(args.draft)), skip={os.path.abspath(args.draft)})
    for n, body in split_episodes(text).items():
        for k, c in stock_uses(body).items():
            near = [m for m in others.get(k, []) if 0 < n - m < STOCK_GAP]
            if c > 1:
                out.append(f"第{n}集「{k}」这类反应用了 {c} 次，一集只留一次，其余换成这个人自己的动作或一句话")
            elif near:
                out.append(f"第{n}集又用了「{k}」这类反应，第{near[-1]}集刚用过（{STOCK_GAP} 集内不重复），换成这个人自己的反应")
    # 只给前 20 条：改完再跑一次就会报剩下的，一次贴几十条只是让每一轮的上下文更长
    rep = {"passed": not out, "count": len(out), "fix": out[:20]}
    if len(out) > 20:
        rep["more"] = f"还有 {len(out) - 20} 条，先改这 20 条再跑"
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0 if not out else 2


def cmd_next(args):
    """看项目目录里已经有什么，只告诉下一步做哪一件事、跑哪条命令。每一步先跑它，不用记整份流程。"""
    P = args.project
    ex = os.path.join(P, "extract")
    me = os.path.abspath(__file__)

    def say(step, todo, cmd=None, model=None, why=None, session=None):
        r = {"step": step, "todo": todo, "cmd": cmd}
        if model:
            r["model"] = TIER_TEXT[model] + (f"（{'、'.join(why)}）" if why else "")
        if session:
            r["session"] = session
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    mpath = os.path.join(ex, "manifest.json")
    if not os.path.exists(mpath):
        return say("1 提取", "原剧还没落盘。把拉片模板（整份文件或逐集 JSON 目录）交给 source。",
                   f"python3 {me} source <模板文件或目录> --out {ex}")
    m = load_sheet(mpath)
    window = [n for n in parse_range(args.range) if n in m["present"]] if args.range else m["present"]
    nobeat = [n for n in window if not os.path.exists(os.path.join(ex, "beats", f"ep-{n:03d}.json"))]
    if nobeat:
        r = f"{nobeat[0]}-{nobeat[min(len(nobeat), 10) - 1]}"
        return say("1 提取", f"第 {r} 集还没有节拍骨架。生成骨架，再逐集读 source/ep-NNN.txt 填空。",
                   f"python3 {me} scaffold {r} --extract {ex}")
    unfilled = []
    for n in window:
        j = load_sheet(os.path.join(ex, "beats", f"ep-{n:03d}.json"))
        if not j.get("hook") or any(not b.get("function") for b in j["beats"]):
            unfilled.append(n)
    if unfilled:
        return say("1 提取", f"这些集的节拍骨架还没填完：{unfilled}。填 function、craft、hook，按剧情调整 turns。")
    ba = os.path.join(P, "beats-all.json")
    stale = not os.path.exists(ba) or any(
        os.path.getmtime(os.path.join(ex, "beats", f"ep-{n:03d}.json")) > os.path.getmtime(ba) for n in window)
    if stale:
        base = os.path.join(P, "beat-sheet.json")
        return say("1 提取", "合成节拍表（会顺带生成台词结构图），然后跑 sheet。" +
                   ("" if os.path.exists(base) else f"先建 {base}：只写 source、roles（功能位），episodes 留空。"),
                   f"python3 {me} build {ex} {base} --out-beats {ba} --out-fp {os.path.join(P, 'fingerprints-all.json')} && "
                   f"python3 {me} sheet {ba} --manifest {mpath}" + (f" --range {args.range}" if args.range else ""))
    _, sh = _run(cmd_sheet, sheet=ba, manifest=mpath, min_beats=4, range=args.range)
    if not sh.get("passed"):
        return say("1 提取", "节拍表没过，按下面逐条改 beats/ep-NNN.json，改完重新 build。不许改 gaps 凑通过。",
                   {"problems": sh.get("problems")})
    for f, step, todo in (("bible.md", "2 外壳", "出 3 个外壳候选给用户选（只写概念，做金手指能力对位）。用户选定后写 bible.md。"),
                          ("season-map.md", "3 地图", "写全季实现地图 season-map.md。")):
        if not os.path.exists(os.path.join(P, f)):
            return say(step, todo)
    cpath = os.path.join(ex, "cast.json")
    cast = load_sheet(cpath) if os.path.exists(cpath) else {}
    need = {sp for n in window for sp in m["episodes"][str(n)]["speakers"]}
    if not cast or any(not cast.get(sp) for sp in need):
        return say("3 地图", "填选角表：原剧每个说话人对应新剧谁。", f"python3 {me} cast {window[0]}-{window[-1]} --extract {ex}")
    mute = voiceless_leads(P, m, window, cast)
    if mute:
        return say("3 地图", f"bible.md 里这些主要人物还没有示例台词：{'、'.join(mute)}。在每人的小节里补「说话：」一行"
                   "（句子长短、口头禅、方言词、怎么骂人怎么服软）和「示例台词：」2-3 句，各人之间要听得出差别。任务包会按本集出场的人带上。")
    approved = os.path.join(P, "approved-sample.txt")
    out = os.path.join(P, "out")
    sheet_eps = {e["ep"]: e for e in load_sheet(ba).get("episodes", [])}
    last_ep = max(int(k) for k in m["episodes"])
    apath = os.path.join(out, "attempts.json")
    attempts = load_sheet(apath) if os.path.exists(apath) else {}
    # 一次只发一集：上一集 check 没过，不给下一集
    for i, n in enumerate(window):
        if i == 1 and not os.path.exists(approved):
            return say("4 样集", f"第 {window[0]} 集样集写完了，交给用户看。用户认可后，把用户的原话写进 {approved}，再继续。")
        draft, impl = episode_files(out, n)
        if not os.path.exists(draft):
            tier, why = model_tier(n, load_sheet(ba), sheet_eps, last_ep)
            fresh = (f"第 {n} 集开新一卷。当前会话已经写过上一卷的话，先开新会话，只带一句：用 drama-clone 技能继续项目 {P}，先跑 next"
                     f"{f' --min-total {args.min_total}' if args.min_total else ''}。进度都在磁盘上，不用带别的。"
                     if i > 1 and (n - window[0]) % VOLUME == 0 else None)
            return say("4 正文", f"生成第 {n} 集的任务包，读一次 out/brief-{n:03d}.md 就开写，这一轮只写这一集，写完跑包里的 check 命令。",
                       f"python3 {me} brief {n} --extract {ex} --sheet {ba} --out {out}"
                       + (f" --min-total {args.min_total}" if args.min_total else "")
                       + (f" --sec {args.sec}" if args.sec else ""), model=tier, why=why, session=fresh)
        code, res = _run(cmd_check, draft=draft, extract=ex, sheet=ba, impl=impl, min_total=args.min_total, sec=args.sec)
        if code:
            # 每个写过台词、没过的版本记一次（空骨架不算）；同一集改了两版还没过，升主力模型
            with open(draft, "rb") as f:
                raw = f.read()
            h = hashlib.sha1(raw).hexdigest()[:12]
            seen = attempts.setdefault(str(n), [])
            if h not in seen and any(SPEECH.match(l) for l in raw.decode("utf-8").splitlines()):
                seen.append(h)
                os.makedirs(out, exist_ok=True)
                with open(apath, "w", encoding="utf-8") as f:
                    json.dump(attempts, f, ensure_ascii=False, indent=1)
            tier, why = model_tier(n, load_sheet(ba), sheet_eps, last_ep, len(seen))
            return say("4 正文", f"第 {n} 集还有要改的地方（没写的拍、用「略」顶替的也在里面），改完再跑 next。",
                       {"draft": draft, "fix": res.get("fix")}, model=tier, why=why)
    return say("5 交付", "全部集检查通过。合并成一份全季稿，出对照表给用户审，再出 Word。",
               f"python3 {me} gate <合并稿> --extract {ex} --sheet {ba} --pair-out 对照.md")


VOLUME = 10  # 正文每 10 集一卷，卷首提示开新会话：上下文越攒越长，每一轮都要重读，越写越贵越慢


def cmd_progress(args):
    """给主线程看的一页进度：每集一行，写没写、过没过、字数多少、该用哪档模型。主线程汇报只用它，不读正文和长 JSON。"""
    P = args.project
    ex, out, ba = os.path.join(P, "extract"), os.path.join(P, "out"), os.path.join(P, "beats-all.json")
    m = load_sheet(os.path.join(ex, "manifest.json"))
    sheet = load_sheet(ba)
    sheet_eps = {e["ep"]: e for e in sheet.get("episodes", [])}
    last_ep = max(int(k) for k in m["episodes"])
    apath = os.path.join(out, "attempts.json")
    attempts = load_sheet(apath) if os.path.exists(apath) else {}
    window = [n for n in parse_range(args.range) if n in m["present"]] if args.range else m["present"]
    rows, todo = [], []
    for n in window:
        draft, impl = episode_files(out, n)
        tier, _ = model_tier(n, sheet, sheet_eps, last_ep, len(attempts.get(str(n), [])))
        if not os.path.exists(draft):
            todo.append(n)
            continue
        code, res = _run(cmd_check, draft=draft, extract=ex, sheet=ba, impl=impl, min_total=args.min_total, sec=args.sec)
        with open(draft, encoding="utf-8") as f:
            st = episode_stats(n, split_episodes(f.read()).get(n, ""))
        verdict = "过" if not code else f"没过 {res.get('count', 0)} 条"
        rows.append(f"| {n} | {verdict} | {st['totalHan']} | {st['speechHan']} | "
                    f"{'主力' if tier == 'main' else '轻量'} |")
    done = [r for r in rows if "| 过 |" in r]
    stock = season_stock(out)
    heavy = sorted(((k, v) for k, v in stock.items() if len(v) > max(1, len(window) // STOCK_GAP)), key=lambda x: -len(x[1]))
    print("\n".join([f"已过 {len(done)} 集，没过 {len(rows) - len(done)} 集，没写 {len(todo)} 集"
                     + (f"（{todo[0]}-{todo[-1]}）" if todo else ""),
                     "套路反应超量（每 10 集最多一次）：" + ("；".join(f"「{k}」{len(v)} 集" for k, v in heavy) if heavy else "无"), "",
                     "| 集 | check | 全文字数 | 口播字数 | 模型 |", "|---|---|---|---|---|", *rows]))
    return 0 if len(done) == len(window) else 2


def episode_files(out, n):
    """第 n 集的正文和实现表。新项目一集一个文件；1.3 及以前按批生成的 draft-AAA-BBB.md 也认。"""
    import glob
    one = os.path.join(out, f"draft-{n:03d}.md")
    if not os.path.exists(one):
        for p in glob.glob(os.path.join(out, "draft-*-*.md")):
            a, b = re.findall(r"(\d{3})-(\d{3})\.md$", p)[0]
            if int(a) <= n <= int(b):
                return p, p.replace("draft-", "impl-")
    return one, os.path.join(out, f"impl-{n:03d}.md")

def main():
    ap = argparse.ArgumentParser(description="DramaClone 检查工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("next", help="看项目进度，只给下一步做什么、跑什么命令")
    p.add_argument("--project", default=".")
    p.add_argument("--range", help="这一轮要做的集数，如 1-14；不给就是全季")
    p.add_argument("--batch", type=int, help="已停用：正文一次只发一集。留着只为旧命令不报错")
    p.add_argument("--min-total", type=int, help="每集全文字数下限（和用户定的）")
    p.add_argument("--sec", type=int, help="单集时长上限（秒），用户明确要求压缩时才给")
    p = sub.add_parser("progress", help="一页进度表：每集过没过、全文/口播字数、模型档，主线程汇报用")
    p.add_argument("--project", default=".")
    p.add_argument("--range")
    p.add_argument("--min-total", type=int)
    p.add_argument("--sec", type=int)
    p = sub.add_parser("scaffold", help="生成预填的节拍骨架（原剧钩子、轮次切片已填好）")
    p.add_argument("range")
    p.add_argument("--extract", required=True)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("cast", help="生成/补全 原剧说话人→新剧人名 的选角表")
    p.add_argument("range")
    p.add_argument("--extract", required=True)
    p = sub.add_parser("brief", help="逐集生成写手任务单 + 正文骨架 + 实现表骨架（一集一套文件）")
    p.add_argument("range")
    p.add_argument("--extract", required=True)
    p.add_argument("--sheet", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--force", action="store_true", help="覆盖已有的正文/实现表骨架（任务单总是重写）")
    p.add_argument("--min-total", type=int, help="每集全文字数下限，写进任务包里的 check 命令")
    p.add_argument("--sec", type=int, help="单集时长上限（秒）。不给就照原剧每集时长；用户或制作方明确要压时才给")
    p = sub.add_parser("check", help="写完一集马上跑：五项检查合一，只列要改的地方")
    p.add_argument("draft")
    p.add_argument("--extract", required=True)
    p.add_argument("--sheet", required=True)
    p.add_argument("--impl")
    p.add_argument("--min-total", type=int)
    p.add_argument("--sec", type=int, help="单集时长上限（秒）；不给就只和原剧比（不超过原剧口播的 1.3 倍）")
    p = sub.add_parser("presence", help="出场逻辑：场内在场一致、每集出场对原剧名册、离场后回来要交代")
    p.add_argument("draft")
    p.add_argument("--extract", required=True)
    p.add_argument("--sheet", required=True)
    p.add_argument("--impl", help="实现表；同目录的 impl-*.md 会一起读，用来认「加人/离场/回归」声明")
    p = sub.add_parser("source", help="把拉片模板落成逐集原文 + manifest + 查重语料")
    p.add_argument("input", help="整份模板 JSON，或逐集 evidence JSON 所在目录")
    p.add_argument("--out", required=True, help="extract 目录")
    p = sub.add_parser("sheet", help="校验节拍表格式，并检查节拍里有没有混进原剧专名")
    p.add_argument("sheet")
    p.add_argument("--manifest", help="source 生成的 manifest.json，用来核对 gaps")
    p.add_argument("--min-beats", type=int, default=4, help="每集节拍下限，默认 4")
    p.add_argument("--range", help="分批提取时只核这一段，如 1-14；交付全季前不带它再跑一次")
    p = sub.add_parser("align", help="集纲与节拍表的逐集对齐率")
    p.add_argument("sheet")
    p.add_argument("draft")
    p.add_argument("--min", type=float, default=0.85, help="对齐率下限，默认 0.85")
    p = sub.add_parser("fingerprint", help="扫描稿件里的原剧指纹词")
    p.add_argument("sheet")
    p.add_argument("draft")
    p.add_argument("--ignore", help="逗号分隔，确认是公共词的指纹")
    p.add_argument("--manifest", help="把原剧说话人名（含去姓变体）也加进指纹")
    p = sub.add_parser("voice", help="每集全文字数、口播字数、场数、括注套路、AI 腔；给阈值就成闸门")
    p.add_argument("draft")
    p.add_argument("--min-total", type=int, help="每集全文汉字下限（含 △ 和括注）")
    p.add_argument("--min-speech", type=int, help="每集口播汉字下限")
    p.add_argument("--max-speech", type=int, help="每集口播汉字上限")
    p.add_argument("--max-tics", type=int, help="每集 AI 腔命中上限，交付时用 0")
    p.add_argument("--max-run", type=int, help="同一人连说行数上限（中间没动作没接话），建议 3")
    p = sub.add_parser("rules", help="客户制作规则：每场说话人数、单句长度")
    p.add_argument("draft")
    p.add_argument("--max-speakers", type=int, default=4)
    p.add_argument("--max-han", type=int, default=20)
    p.add_argument("--require-annotation", action="store_true", help="项目要求句句带括注时才开")
    p = sub.add_parser("dup", help="字面查重：列出与原剧语料重合的 k 字片段")
    p.add_argument("draft")
    p.add_argument("source")
    p.add_argument("--k", type=int, default=8)
    p = sub.add_parser("build", help="合成全季节拍表和指纹表")
    p.add_argument("extract")
    p.add_argument("base")
    p.add_argument("--out-beats", required=True)
    p.add_argument("--out-fp", required=True)
    p = sub.add_parser("gate", help="闸门：前置产物、体量对原剧、钩子对位；可出逐句对照表")
    p.add_argument("draft")
    p.add_argument("--extract", required=True)
    p.add_argument("--sheet", required=True, help="build 合成的 beats-all.json")
    p.add_argument("--impl", help="实现表；给了就检查原剧钩子/新剧钩子两行")
    p.add_argument("--pair-out", help="输出原剧/新剧逐句对照 md，给人审")
    p.add_argument("--min-line-ratio", type=float, default=0.7, help="新剧台词行数 / 原剧台词轮数 下限")
    p.add_argument("--min-speech-ratio", type=float, default=0.6, help="新剧口播字数 / 原剧口播字数 下限")
    p.add_argument("--max-speech-ratio", type=float, default=1.3, help="新剧口播字数 / 原剧口播字数 上限（时长照原剧）")
    args = ap.parse_args()
    try:
        return {"sheet": cmd_sheet, "align": cmd_align, "fingerprint": cmd_fingerprint, "voice": cmd_voice,
                "rules": cmd_rules, "dup": cmd_dup, "build": cmd_build,
                "source": cmd_source, "gate": cmd_gate, "next": cmd_next, "scaffold": cmd_scaffold,
                "cast": cmd_cast, "brief": cmd_brief, "check": cmd_check, "presence": cmd_presence,
                "progress": cmd_progress}[args.cmd](args)
    except (OSError, ValueError, KeyError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
