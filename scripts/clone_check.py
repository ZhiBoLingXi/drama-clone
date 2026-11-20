#!/usr/bin/env python3
"""DramaClone 检查工具：节拍表校验、节拍对齐、指纹扫描。只用标准库，不联网。

  clone_check.py sheet <beat-sheet.json>
  clone_check.py align <beat-sheet.json> <集纲.md> [--min 0.85]
  clone_check.py fingerprint <beat-sheet.json> <稿件.md> [--ignore 词1,词2]
  clone_check.py voice <正文.md> [--min-total N] [--min-speech N] [--max-speech N] [--max-tics N]
  clone_check.py rules <正文.md> [--max-speakers 4] [--max-han 20] [--require-annotation]
  clone_check.py dup <新稿.md> <原剧语料.txt> [--k 8]
  clone_check.py build <extract目录> <beat-sheet.json> --out-beats beats-all.json --out-fp fingerprints-all.json

退出码：0 通过；1 输入错误；2 有违反项。输出为 JSON。
"""
import argparse
import json
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


def split_episodes(text):
    """返回 {集号: 该集文本}。"""
    heads = list(EP_HEAD.finditer(text))
    out = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out[cn_to_int(m.group(1))] = text[m.start():end]
    return out


def fingerprint_terms(sheet):
    terms = {}
    for fp in sheet.get("fingerprints", []):
        for t in fp.get("terms", []):
            t = t.strip()
            if len(t) >= 2:
                terms[t] = fp.get("id", "?")
    for r in sheet.get("roles", []):
        name = (r.get("sourceName") or "").strip()
        if len(name) >= 2:
            terms.setdefault(name, r.get("id", "?"))
    return terms


def cmd_sheet(args):
    sheet = load_sheet(args.sheet)
    problems = []
    terms = fingerprint_terms(sheet)
    role_ids = {r.get("id") for r in sheet.get("roles", [])}
    seen = set()
    for ep in sheet.get("episodes", []):
        n = ep.get("ep")
        if n in seen:
            problems.append(f"第{n}集重复")
        seen.add(n)
        if not ep.get("beats"):
            problems.append(f"第{n}集没有节拍")
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
    if isinstance(total, int):
        missing = [i for i in range(1, total + 1) if i not in seen and i not in gaps]
        if missing:
            problems.append(f"既不在 episodes 也不在 gaps 的集：{missing}")
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
        text = f.read()
    ignore = {t for t in (args.ignore or "").split(",") if t}
    eps = split_episodes(text) or {0: text}
    hits = []
    for term, fid in fingerprint_terms(sheet).items():
        if term in ignore:
            continue
        for n, body in eps.items():
            for m in re.finditer(re.escape(term), body):
                s = max(0, m.start() - 12)
                hits.append({"term": term, "fingerprint": fid, "ep": n,
                             "context": body[s:m.end() + 12].replace("\n", " ")})
    report = {"terms": len(set(fingerprint_terms(sheet)) - ignore), "hits": hits,
              "ignored": sorted(ignore), "passed": not hits}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not hits else 2


SPEECH = re.compile(r"^([^△场人#\s][^：（]{0,20})(（[^）]*）)?：(.*)$")
AI_TICS = ["像", "如同", "仿佛", "宛如", "等于", "意味着", "象征", "一字一顿"]
# 括注和 △ 里都算：文学腔、心理旁白、“一丝/格外/显得”这类虚写
AI_TICS_ANY = ["仿佛", "如同", "宛如", "像是", "似乎", "心理侧写", "难以察觉", "闪过一丝", "掠过一丝", "一丝弧度", "格外", "显得",
               "眼底", "嘴角勾起", "唇角", "意味深长", "空气凝固", "空气中弥漫"]
HAN = re.compile("[一-鿿]")


def episode_stats(n, text):
    lines = text.splitlines()
    speech = [m for m in (SPEECH.match(l) for l in lines) if m]
    speech_han = sum(len(HAN.findall(re.sub(r"（[^）]*）", "", m.group(3)))) for m in speech)
    # 全文字数：本集正文里的全部汉字（场头、人物行、△、括注、台词都算），即用户和客户口中的“剧本字数”
    body = "\n".join(l for l in lines if not EP_HEAD.match(l))
    parens = [m.group(2) for m in speech if m.group(2)]
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
            "aiTics": tics}


def cmd_voice(args):
    with open(args.draft, encoding="utf-8") as f:
        eps = split_episodes(f.read())
    if not eps:
        print(json.dumps({"error": "没找到 `# 第N集` 标题，按集统计不了"}, ensure_ascii=False))
        return 1
    rows = [episode_stats(n, eps[n]) for n in sorted(eps)]
    gated = any(v is not None for v in (args.min_total, args.min_speech, args.max_speech, args.max_tics))
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
        if why:
            fails.append({"ep": r["ep"], "why": why})
    totals = [r["totalHan"] for r in rows]
    report = {"episodes": rows,
              "summary": {"count": len(rows), "totalHanMin": min(totals), "totalHanMax": max(totals),
                          "totalHanMedian": sorted(totals)[len(totals) // 2]},
              "failed": fails}
    if gated:
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


def cmd_rules(args):
    """客户制作规则：每场说话人数、单句汉字数；括注只在 --require-annotation 时判。"""
    with open(args.draft, encoding="utf-8") as f:
        lines = f.read().splitlines()
    scene, speakers, over, long_, nop = None, {}, [], [], []
    for i, l in enumerate(lines, 1):
        if l.startswith("场"):
            scene = l.split()[0]
            speakers[scene] = set()
            continue
        m = SPEECH.match(l)
        if not (m and scene):
            continue
        speakers[scene].add(m.group(1))
        han = len(re.findall(r"[\u4e00-\u9fff]", m.group(3)))
        if han > args.max_han:
            long_.append({"line": i, "speaker": m.group(1), "han": han})
        if not m.group(2):
            nop.append({"line": i, "text": l[:30]})
    over = [{"scene": k, "speakers": sorted(v)} for k, v in speakers.items() if len(v) > args.max_speakers]
    report = {"tooManySpeakers": over, "tooLong": long_, "noAnnotation": nop,
              "passed": not (over or long_ or (nop and args.require_annotation))}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


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
    for p in sorted(glob.glob(os.path.join(args.extract, "beats", "ep-*.json"))):
        j = load_sheet(p)
        n = j["ep"]
        eps.setdefault(n, {"ep": n, "beats": j["beats"], "hook": j.get("hook", ""), "climax": bool(j.get("climax"))})
        terms = [t for t in j.get("fingerprints", []) if isinstance(t, str) and 4 <= len(t) <= 30]
        fps.append({"id": f"F-E{n}", "kind": "其他", "episodes": [n], "terms": terms})
        for c in j.get("newCharacters", []):
            s = (c.get("sourceName") or "").strip()
            if 2 <= len(s) <= 4 and s not in GENERIC_ROLES and re.fullmatch(r"[\u4e00-\u9fff]+", s):
                names.add(s)
    fps.append({"id": "F-NAMES", "kind": "人名", "terms": sorted(names)})
    out = {"source": base.get("source"), "totalEpisodes": max(eps), "roles": base.get("roles", []),
           "episodes": [eps[k] for k in sorted(eps)], "gaps": base.get("gaps", []), "fingerprints": fps}
    with open(args.out_beats, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open(args.out_fp, "w", encoding="utf-8") as f:
        json.dump({"fingerprints": fps, "roles": [], "episodes": []}, f, ensure_ascii=False, indent=1)
    print(json.dumps({"episodes": len(eps), "beats": sum(len(e["beats"]) for e in eps.values()),
                      "names": len(names), "missing": [i for i in range(1, max(eps) + 1) if i not in eps]},
                     ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser(description="DramaClone 检查工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sheet", help="校验节拍表格式，并检查节拍里有没有混进原剧专名")
    p.add_argument("sheet")
    p = sub.add_parser("align", help="集纲与节拍表的逐集对齐率")
    p.add_argument("sheet")
    p.add_argument("draft")
    p.add_argument("--min", type=float, default=0.85, help="对齐率下限，默认 0.85")
    p = sub.add_parser("fingerprint", help="扫描稿件里的原剧指纹词")
    p.add_argument("sheet")
    p.add_argument("draft")
    p.add_argument("--ignore", help="逗号分隔，确认是公共词的指纹")
    p = sub.add_parser("voice", help="每集全文字数、口播字数、场数、括注套路、AI 腔；给阈值就成闸门")
    p.add_argument("draft")
    p.add_argument("--min-total", type=int, help="每集全文汉字下限（含 △ 和括注）")
    p.add_argument("--min-speech", type=int, help="每集口播汉字下限")
    p.add_argument("--max-speech", type=int, help="每集口播汉字上限")
    p.add_argument("--max-tics", type=int, help="每集 AI 腔命中上限，交付时用 0")
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
    args = ap.parse_args()
    try:
        return {"sheet": cmd_sheet, "align": cmd_align, "fingerprint": cmd_fingerprint, "voice": cmd_voice,
                "rules": cmd_rules, "dup": cmd_dup, "build": cmd_build}[args.cmd](args)
    except (OSError, ValueError, KeyError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
