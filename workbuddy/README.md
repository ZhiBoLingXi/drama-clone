# 高仿编剧（drama-clone-expert）

WorkBuddy 专家包。把 drama-clone 技能装进一个专家：系统提示词里写死"每步先跑 next、填骨架、一次写一集、写一集查一集"，
预加载技能，声明 mali-story 连接器依赖（召唤专家前引导用户完成 OAuth），maxTurns 提到 400（默认 50 跑不完一季）。

## 打包
这个目录只放专家包自己的源文件。`skills/drama-clone` 不入库，打包时从仓库根目录现拷，保证专家包里的技能和仓库同版本：

```bash
./pack.sh        # 在仓库根目录跑，产出 dist/drama-clone-v<版本>.zip 和 dist/drama-clone-expert-v<版本>.zip
```

## 提交前还缺
- `avatars/expert.png`：512×512 PNG，≤500KB，漫画/插画风格。
- 在 WorkBuddy 里实测一遍：召唤专家 → 连接 mali-story → 用快捷提示词输入剧名 → 走到第 1 集样集，再连写 20 集左右，看 `voice` 报的每集字数有没有往后缩水。

## 模型
专家包不能指定模型，技能里的「按集分模型」在 WorkBuddy 上只能靠用户在对话框里切：`next` 的 `model` 字段写着主力模型时
（前 10 集、小高潮、总弹簧、大结局、改了两版没过的集），用强模型（本机可选 claude-sonnet-5、gpt-6.2-sol、gemini-3.1-pro-preview）；
其余的集可以用轻量模型。2026-11-20 那次后面几集字数不足、出现"略"的会话用的是 gemini-3.8-flash，而且是一次写一整批。
