"""公文生成后处理器（V1.3 验收验证过的规则，服务端化）。

原则：
- 当前文件文号、成文日期由程序决定，LLM 禁止自由生成
- 历史政策文号/日期允许正常引用，只做格式规范化
- 只处理当前文档自己的文号和落款，不粗暴全文替换
"""
import re
import unicodedata
from datetime import date
from typing import Dict, List, Optional, Tuple

from app.core.config import settings

TODAY = date.today()
TODAY_STR = f"{TODAY.year}年{TODAY.month}月{TODAY.day}日"

# ---------- 日期识别 ----------

DATE_PATTERNS = [
    r"20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日",
    r"[二〇零○一二三四五六七八九]{4}\s*年\s*"
    r"[正一二三四五六七八九十]{1,3}\s*月\s*"
    r"[一二三四五六七八九十廿卅]{1,4}\s*日",
]

CN_DIGIT = {
    "零": 0, "〇": 0, "○": 0, "一": 1, "二": 2, "三": 3,
    "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def normalize_width(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _parse_date_year(date_str: str) -> Optional[int]:
    m = re.search(r"(20\d{2})\s*年", date_str)
    if m:
        return int(m.group(1))
    m = re.search(r"([二〇零○一二三四五六七八九]{4})\s*年", date_str)
    if m:
        return int("".join(str(CN_DIGIT[c]) for c in m.group(1)))
    return None


# ---------- 历史文号格式规范化 ----------

DOCNUM_LOOSE_RE = re.compile(
    r"([\u4e00-\u9fa5]{1,10})"       # 机关代字
    r"[〔\[【［]"
    r"([0-9０-９OoＯｏIl\s]{1,12})"  # 年份部分
    r"[〕\]】］\]]"
    r"\s*([0-9０-９OoＯｏIl\s]{1,8})"  # 序号部分
    r"\s*[号好]"
)


def _clean_num_part(s: str, letter_map: Dict[str, str]) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    for src, dst in letter_map.items():
        s = s.replace(src, dst)
    return s


def normalize_document_numbers(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """机械修复引用文号格式污染。年份不合理（2106/212）不猜测。"""
    fixes: List[Tuple[str, str]] = []

    def repl(m: "re.Match") -> str:
        prefix, year_raw, num_raw = m.groups()
        year = _clean_num_part(
            year_raw, {"O": "0", "o": "0", "l": "1", "I": "1"})
        num = _clean_num_part(
            num_raw, {"O": "0", "o": "0", "l": "1", "I": "1"})
        if not year.isdigit() or not num.isdigit():
            return m.group(0)
        if not (len(year) == 4 and 1949 <= int(year) <= TODAY.year + 1):
            return m.group(0)
        new = f"{prefix}〔{year}〕{num}号"
        if new != m.group(0):
            fixes.append((m.group(0), new))
        return new

    return DOCNUM_LOOSE_RE.sub(repl, text), fixes


# ---------- 当前文号：剥离模型自写 + 程序注入 ----------

HEADER_DOCNUM_LINE_RE = re.compile(
    r"^[\u4e00-\u9fa5]{0,10}\s*"
    r"[〔\[【［][^〕\]】］\]\n]{1,15}[〕\]】］\]]?"
    r"\s*[0-9０-９OoＯｏIl\s]{0,8}\s*[号好]?$"
)

SIGNOFF_LINE_RE = re.compile(
    r"^[\u4e00-\u9fa5]{2,20}"
    r"(政府|办公厅|办公室|委员会|局|厅|部|署)$"
)

DOCNUM_DAIZI_MAP = [
    ("国务院办公厅", "国办发"),
    ("国务院", "国发"),
    ("广东省人民政府办公厅", "粤府办"),
    ("广东省人民政府", "粤府"),
    ("人民政府办公厅", "政办发"),
    ("人民政府", "政发"),
    ("司法局", "司发"),
    ("司法厅", "司发"),
    ("办公厅", "政办发"),
    ("局", "局发"),
    ("厅", "厅发"),
]


def derive_daizi(text: str) -> str:
    """从落款单位推导文号代字，兜底用配置值。"""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in reversed(lines):
        if SIGNOFF_LINE_RE.match(line):
            for key, daizi in DOCNUM_DAIZI_MAP:
                if key in line:
                    return daizi
            break
    return settings.DOC_NUMBER_DEFAULT_DAIZI


def strip_header_docnum(text: str) -> Tuple[str, Optional[str]]:
    """移除模型在文头（前 6 个非空行）自写的独立文号行。"""
    lines = text.split("\n")
    nonempty_idx = [i for i, l in enumerate(lines) if l.strip()]
    stripped = None
    for i in nonempty_idx[:6]:
        line = lines[i].strip()
        if HEADER_DOCNUM_LINE_RE.match(line) and (
            "〔" in line or "［" in line or "[" in line or "【" in line
        ):
            stripped = line
            lines[i] = ""
            break
    return "\n".join(lines), stripped


def inject_docnum(text: str, docnum: str) -> str:
    """在标题行之后插入程序生成的文号行。"""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip():
            lines.insert(i + 1, docnum)
            return "\n".join(lines)
    return docnum + "\n" + text


# ---------- 落款日期 ----------

def fix_signoff_date(text: str, target: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """文末 200 字内的落款日期偏离目标日期（默认今天）→ 替换。
    正文中的历史引用日期不受影响。"""
    target = target or TODAY_STR
    normalized = normalize_width(text)
    matches = []
    for pattern in DATE_PATTERNS:
        matches.extend(re.finditer(pattern, normalized))
    if not matches:
        return text, None
    last = matches[-1]
    if last.start() < len(normalized) - 200:
        return text, None
    if normalize_width(last.group(0)).replace(" ", "") == target:
        return text, None
    if target == TODAY_STR:
        year = _parse_date_year(last.group(0))
        if year is None or (TODAY.year - 1 <= year <= TODAY.year + 1):
            return text, None
    old = last.group(0)
    return text[:last.start()] + target + text[last.end():], \
        f"落款日期校正：{old} → {target}"


def ensure_signoff_date(text: str, target: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """有落款单位但缺成文日期时，在落款后补目标日期（默认今天）。"""
    target = target or TODAY_STR
    lines = text.split("\n")
    for i in range(len(lines) - 1, max(len(lines) - 8, -1), -1):
        if SIGNOFF_LINE_RE.match(lines[i].strip()):
            following = "\n".join(lines[i + 1:i + 3])
            if not any(re.search(p, following) for p in DATE_PATTERNS):
                lines.insert(i + 1, target)
                return "\n".join(lines), f"补充成文日期：{target}"
            return text, None
    return text, None


# ---------- 数字与日期微修 ----------

FULLWIDTH_DIGIT_MAP = {ord("０") + i: ord("0") + i for i in range(10)}


def normalize_fullwidth_digits(text: str) -> Tuple[str, Optional[str]]:
    """公文国标要求阿拉伯数字用半角。"""
    new = text.translate(FULLWIDTH_DIGIT_MAP)
    if new != text:
        n = sum(1 for a, b in zip(text, new) if a != b)
        return new, f"全角数字规范化 {n} 处"
    return text, None


def fix_date_typos(text: str) -> Tuple[str, List[str]]:
    """窄模式日期错字修复。"""
    events = []
    new = re.sub(r"(20\d{2})\s*平(?=\s*\d)", r"\1年", text)
    if new != text:
        events.append("日期错字修复：“平”→“年”")
    text = new
    new = re.sub(r"(20\d{2}年\d{1,2}—\d{1,2})(?=\s*[）)])", r"\1月", text)
    if new != text:
        events.append("日期区间补“月”")
    return new, events


# ---------- 占位符 / 退化 / 截断 / 乱码检测 ----------

PLACEHOLDER_PATTERNS = [
    r"待补充", r"待完善", r"待填写", r"待确定", r"待添加",
    r"[XxＸｘ×]{2,}年[XxＸｘ×]{1,}月",
    r"[XxＸｘ×]{1,}月[XxＸｘ×]{1,}日",
    r"[XxＸｘ×]{2,}〔", r"[XxＸｘ×]{2,}号",
    r"××+", r"ＸＸ+", r"_{3,}", r"＿{2,}", r"《\s*》", r"〔\s*〕",
]


def detect_placeholders(text: str) -> List[str]:
    matches = []
    for pattern in PLACEHOLDER_PATTERNS:
        matches.extend(
            m if isinstance(m, str) else "".join(m)
            for m in re.findall(pattern, text)
        )
    return list(dict.fromkeys(matches))


def detect_degeneration(text: str) -> Optional[str]:
    m = re.search(r"(.{8,60}?)\1{2,}", text, flags=re.DOTALL)
    if m:
        return "连续重复片段"
    plain = re.sub(r"\s+", "", text)
    window, worst, low = 300, 1.0, 0
    for start in range(0, max(len(plain) - window, 1), 150):
        seg = plain[start:start + window]
        grams = [seg[i:i + 4] for i in range(len(seg) - 3)]
        if not grams:
            continue
        diversity = len(set(grams)) / len(grams)
        worst = min(worst, diversity)
        if diversity < 0.35:
            low += 1
    if low >= 3 or worst < 0.28:
        return f"局部文本多样性崩塌（最低 {worst:.2f}）"
    return None


def detect_repetition(text: str) -> Optional[str]:
    counts: Dict[str, int] = {}
    for s in re.split(r"[。；！？\n]", text):
        norm = re.sub(r"[\s，。；、：：（）()《》〈〉\"'“”‘’]", "", s)
        if len(norm) < 20:
            continue
        if "《" in s and "》" in s:
            continue
        if re.search(r"责任单位|完成时限|牵头单位|配合单位", s):
            continue
        counts[norm] = counts.get(norm, 0) + 1
    worst = max(counts.values()) if counts else 0
    if worst >= 4:
        return f"机械重复：同一句最多出现 {worst} 次"
    return None


DANGLING_ENDINGS = (
    "，", "、", "：", ":", "；", ";", "（", "(",
    "一是", "二是", "三是", "四是", "五是", "六是",
    "的", "了", "和", "与", "及", "并",
)


def detect_truncation(text: str) -> Optional[str]:
    tail = text.rstrip()
    if not tail:
        return "空输出"
    for ending in DANGLING_ENDINGS:
        if tail.endswith(ending):
            return f"结尾悬空（以“{ending}”结尾）"
    if tail.count("《") != tail.count("》"):
        return "书名号未闭合"
    return None


def detect_garbled(text: str) -> Optional[str]:
    if " " in text:
        return "含替换符  "
    pua = re.findall(r"[\ue000-\uf8ff]", text)
    if pua:
        return f"含私用区字符 ×{len(pua)}"
    if re.search(r"□{3,}", text):
        return "含连续 □"
    return None


# ---------- 后处理流水线 ----------

class PostProcessor:
    """生成文本后处理：文号/日期程序接管 + 格式污染清理。

    返回 (处理后文本, 事件列表, 文号, 成文日期)。
    """

    def __init__(self, db=None) -> None:
        self.db = db

    def process(
        self,
        text: str,
        signoff_hint: Optional[str] = None,
        doc_number: Optional[str] = None,
        doc_date: Optional[str] = None,
        inject_docnum: bool = True,
        inject_date: bool = True,
    ) -> Tuple[str, List[str], Optional[str], Optional[str]]:
        """后处理。

        文号/日期策略（业务规则）：
        - doc_number 传入用户指定文号 -> 原样注入，绝不改写；
        - inject_docnum=True 且未指定 -> 程序生成（序列号服务）；
        - inject_docnum=False -> 不注入任何文号（默认为关闭）。
        - doc_date 传入用户指定日期 -> 落款使用该日期；
        - inject_date=True -> 修正/补充为系统当天；
        - inject_date=False -> 不补不改成文日期。
        """
        from app.application.writing.doc_number_service import (
            DocNumberService,
        )
        events: List[str] = []

        # 1. 剥离模型自写的文头文号（LLM 禁止自由生成文号）
        text, stripped = strip_header_docnum(text)
        if stripped:
            events.append(f"移除模型自写文号：{stripped[:40]}")

        # 2. 规范化正文引用的历史文号格式污染
        text, fixes = normalize_document_numbers(text)
        if fixes:
            events.append(f"历史文号格式规范化 {len(fixes)} 处")

        # 3. 落款日期：用户指定 > 系统当天 > 不处理
        if doc_date:
            text, date_fix = fix_signoff_date(text, target=doc_date)
            if date_fix:
                events.append(date_fix)
            text, date_add = ensure_signoff_date(text, target=doc_date)
            if date_add:
                events.append(date_add)
        elif inject_date:
            text, date_fix = fix_signoff_date(text)
            if date_fix:
                events.append(date_fix)
            text, date_add = ensure_signoff_date(text)
            if date_add:
                events.append(date_add)

        # 4. 数字与日期微修
        text, fw = normalize_fullwidth_digits(text)
        if fw:
            events.append(fw)
        text, typo_events = fix_date_typos(text)
        events.extend(typo_events)

        # 5. 文号：用户指定 > 程序生成 > 不注入
        out_number: Optional[str] = None
        if doc_number:
            text = inject_docnum(text, doc_number)
            out_number = doc_number
            events.append(f"使用用户指定文号：{doc_number}")
        elif inject_docnum:
            daizi = derive_daizi(signoff_hint or text)
            out_number = DocNumberService(self.db).next_number(daizi)
            text = inject_docnum(text, out_number)
            events.append(f"程序注入文号：{out_number}")

        out_date = doc_date or (TODAY_STR if inject_date else None)
        return text, events, out_number, out_date
