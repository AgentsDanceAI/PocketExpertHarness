# 你的技能

在这里放技能目录, 每个目录一个 `SKILL.md`:

```
skills/
  weekly-report/
    SKILL.md        # 头部 name / description / triggers, 下面写给模型的操作说明
    template.md     # 可选: 附带文件, 模型用 use_skill(name, file="template.md") 读取
```

`triggers` 里的词出现在用户的话里时, 技能会自动加载; 否则模型会根据 description 自己决定要不要用。
格式与 Claude 的 Agent Skills 兼容, 现成的技能包可以直接拷进来。
