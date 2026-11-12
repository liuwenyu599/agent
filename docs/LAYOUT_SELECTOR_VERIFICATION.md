# 选版器重构（`28a429a`）等价性核验

> 目的：把审查对象①「逐分一致是否真的证明旧→新行为等价」从"自洽"升级为"可闭环证明"。
> 结论：**是等价，已用重构前父提交旧代码独立复算闭环。**

## 背景与风险点

重构把 `_layout_score` 的 if/elif 硬编码打分链改成读 `_LAYOUT_AFFINITY` 声明式注册表。
配套 `layout_baseline.json`（684 条 = 36 版式 × 19 slide）冻结了旧行为，`test_layout_score_characterization.py`
用它断言新代码一致。

风险：`layout_baseline.json` 与重构提交 `28a429a` **同提交新增**（git 历史显示三件套
`layout_baseline.json` / `_capture_layout_baseline.py` / `test_layout_score_characterization.py`
均为 `28a429a` 的 `A`dd）。若基线是用新代码导出的，则"684/684 一致"只证明新代码自洽，
**不证明**旧 if/elif → 新注册表等价。测试文件 docstring 声称"重构前导出"，但 git 历史无法佐证。

## 验证方法（绕开 sqlalchemy，纯 AST 抽取）

1. 从当前模块 AST 抽取 `LAYOUT_CATALOG`（36 个 spec，内容重构前后不变）。
2. 从父提交 `78fa1b4` 的 `ppt_engine.py` 用 `ast.get_source_segment` 抽取**旧**
   `_layout_score` + `_slide_has_image`（以及其依赖的小函数），exec 进独立命名空间。
3. 用旧函数对同样的 19 个 slide × 36 spec 重算，与 `layout_baseline.json` 逐条比对（容差 1e-9）。

复现命令（在 `server/` 下，需 git 历史）：

```bash
git show 78fa1b4:server/app/application/ppt/ppt_engine.py > /tmp/old_engine.py
python - <<'PY'
import ast, json
new=open("app/application/ppt/ppt_engine.py",encoding="utf-8").read()
old=open("/tmp/old_engine.py",encoding="utf-8").read()
def get_assign(src,name):
    t=ast.parse(src)
    for n in ast.walk(t):
        if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id==name and n.value is not None:
            return ast.literal_eval(n.value)
        if isinstance(n,ast.Assign):
            for tg in n.targets:
                if isinstance(tg,ast.Name) and tg.id==name: return ast.literal_eval(n.value)
    raise RuntimeError("not found "+name)
def get_func(src,name):
    t=ast.parse(src)
    for n in ast.walk(t):
        if isinstance(n,ast.FunctionDef) and n.name==name: return ast.get_source_segment(src,n)
    raise RuntimeError("not found "+name)
cat=get_assign(new,"LAYOUT_CATALOG")
ns={"Dict":dict,"List":list,"Any":object,"Optional":object}
for f in ("_slide_has_image","_layout_score"):
    s=get_func(old,f)
    try: exec(s,ns)
    except NameError as e:
        ns.update({}); exec(get_func(old,str(e).split("'")[1]),ns); exec(s,ns)
fn=ns["_layout_score"]
# 19 个 slide 同 test_layout_score_characterization.py 的 _BASE
def _mk(p=None,b=None,hi=False):
    s={"points":p or [],"blocks":b or {}}; 
    if hi: s["_image"]={"file_path":"/x.png"}
    return s
BASE={"empty":_mk(),"one_short":_mk(["短句"]),"one_long":_mk(["一"*50]),
 "two_balanced":_mk(["一"*10,"二"*10]),"two_gap":_mk(["一"*50,"二"*5]),
 "three":_mk(["甲","乙","丙"]),"four_short":_mk(["x","y","z","w"]),
 "four_long":_mk(["x"*30,"y"*30,"z"*30,"w"*30]),"five":_mk(["x"]*5),
 "image_two":_mk(["一","二"],hi=True),"quote_match":_mk(["“引用句”","普通"]),
 "quote_no":_mk(["普通","文字"]),"cards3":_mk(b={"cards":[1,2,3]}),
 "cards2":_mk(b={"cards":[1,2]}),"table3":_mk(b={"table":{"rows":[1,2,3]}}),
 "timeline4":_mk(b={"timeline":[1,2,3,4]}),"process5":_mk(b={"process":[1,2,3,4,5]}),
 "sym2_ok":_mk(["一"*10,"二"*10]),"sym2_bad":_mk(["一"*10,"二"*30])}
exp={(d["sid"],d["slide"]):d["score"] for d in json.load(open("tests/layout_baseline.json",encoding="utf-8"))}
mm=0
for specs in cat.values():
    for spec in specs:
        for k,sl in BASE.items():
            g=round(fn(spec,sl,recent=[],used={}),6); e=exp.get((spec["id"],k))
            if e is None or abs(g-e)>1e-9: mm+=1
print("不一致数:",mm)   # 期望 0
PY
```

## 结果

| 项 | 结果 |
|---|---|
| 旧 if/elif 重算 vs 基线 | **684/684 零偏差** → 等价性成立 |
| `_LAYOUT_AFFINITY` 声明版式数 | **18**（注意：非最初审查稿写的 19） |
| 未声明走 `weight` 兜底版式数 | **18**（非 17） |
| `LAYOUT_CATALOG` 总版式数 | **36** |
| 死声明（声明指向不存在版式） | **0** |
| `weight` 范围 | **0.6–1.3**（最高 `section.number`，中性偏保守） |
| 相邻/整篇惩罚对兜底版式 | 生效（`ppt_engine.py:579-581` 在规则循环外） |

## 两处历史遗留（已冻结、非回归，建议加注释避免误读）

1. `image_bonus` 无图时记 `0.0` 而非负分：`content.image_right/left` 无图只拿基础分、不受罚，
   靠 `requires`/适配过滤和 `used` 惩罚间接避让。继承自旧 if 链，基线已冻结。
2. `data.cards` 的 `else` 是 **+0.2（唯一"不匹配也加分"的规则）**：注册表里容易误读，
   建议在 `_LAYOUT_AFFINITY["data.cards"]` 处加一行注释说明这是有意的历史行为。
