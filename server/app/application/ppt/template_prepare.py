"""PPT 模板预处理核心：把外部拿来的模板改成系统可直接使用的形态。

这是 deploy/prepare_ppt_template.py 背后的同一套流水线，抽成服务端可导入模块，
供 upload_template / import_template_url 实现「上传即预处理」。CLI 只是薄封装。

机械改造项（全部确定性规则，不调用模型、不重排版面）：
  · 打 token：{{title}}/{{subtitle}}/{{pointN}}/{{image}} 自动写入
  · 页型标签：改文字前先按原文分类，写入幻灯片备注（PPT_LAYOUT_TYPE:xxx），
    否则「目录」被替换成 {{title}} 后引擎分类线索丢失
  · 统一字体：run 级 + 主题级（中文 Microsoft YaHei / 西文 Times New Roman，不斜体）
  · 去品牌：移除版式/母版层的 logo 图与品牌文字
  · 清示例字：点击输入/汇报人/占位符等脚手架文字
  · 自动去空页：处理完仍无任何 token/图片的页（如纯装饰页）删除
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections import Counter

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

from app.core.fonts import DEFAULT_CJK_FONT, DEFAULT_LATIN_FONT, apply_cjk_font

TARGET_RATIO = 16 / 9
# 与 fonts.py / 迁移 023 一致：中文写 Windows 原生 family（麒麟/容器走
# deploy/fonts/51-ppt-fonts.conf 的 fontconfig 别名），西文单独走 Times New Roman。
DEFAULT_FONT = DEFAULT_CJK_FONT

BRAND_TEXT_HINTS = (".com", ".cn", ".net", ".org", "officeplus",
                    "powered by", "template by", "www.", "http",
                    "design by", "author:", "©", "版权")

# 封面/页脚常见的模板脚手架文字，明确不是内容，处理时清空（保留框位置）。
# 只作用于未被打上 token 的残留文本框，不会误伤 {{...}} 锚点。
SCRUB_HINTS = ("点击输入", "您可以添加", "您可以", "在此输入", "在此处输入",
               "XX月XX日", "XX月", "XXX", "占位符", "占位", "示例文字",
               "汇报人", "汇报时间", "汇报：", "日期：", "officeplus")


class TemplatePrepareError(ValueError):
    """模板预处理失败（文件损坏、比例不符等）。"""


class RatioNotSupported(TemplatePrepareError):
    """页面比例不是 16:9，无法机械处理（重排必须人工做）。"""


def walk(shapes, depth: int = 0):
    for sh in shapes:
        yield sh, depth
        try:
            is_group = sh.shape_type == MSO_SHAPE_TYPE.GROUP
        except Exception:
            is_group = False
        if is_group:
            yield from walk(sh.shapes, depth + 1)


def is_picture(sh) -> bool:
    try:
        return sh.shape_type == MSO_SHAPE_TYPE.PICTURE
    except Exception:
        return False


def text_size(sh) -> float:
    sizes = []
    try:
        for para in sh.text_frame.paragraphs:
            for run in para.runs:
                if run.font.size:
                    sizes.append(run.font.size.pt)
            if para.font.size:
                sizes.append(para.font.size.pt)
    except Exception:
        pass
    return max(sizes) if sizes else 0.0


def pic_hash(sh) -> str:
    try:
        return hashlib.md5(sh.image.blob).hexdigest()[:12]
    except Exception:
        return ""


def has_smartart(sh) -> bool:
    try:
        xml = sh._element.xml
        return "/diagram" in xml or "dgm" in xml
    except Exception:
        return False


def set_text(shape, text: str) -> None:
    """替换文本但保留首段首个 run 的格式，清掉多余段落与 run。"""
    tf = shape.text_frame
    para = tf.paragraphs[0]
    runs = list(para.runs)
    if runs:
        runs[0].text = text
        for run in runs[1:]:
            run._r.getparent().remove(run._r)
    else:
        para.text = text
    for extra in list(tf.paragraphs[1:]):
        extra._p.getparent().remove(extra._p)


def delete_slide(prs, index: int) -> None:
    sld_id_lst = prs.slides._sldIdLst
    sld_id = sld_id_lst[index]
    r_id = sld_id.get(qn("r:id"))
    try:
        prs.part.drop_rel(r_id)
    except Exception:
        pass
    sld_id_lst.remove(sld_id)


def repeated_picture_hashes(prs) -> set:
    """≥60% 页面出现过的图片：系统会判为固定装饰，不适合当内容图锚点。"""
    counter = {}
    total = len(prs.slides)
    for slide in prs.slides:
        seen = set()
        for sh, _ in walk(slide.shapes):
            if is_picture(sh):
                seen.add(pic_hash(sh))
        for h in seen:
            if h:
                counter[h] = counter.get(h, 0) + 1
    threshold = max(3, int(total * 0.6))
    return {h for h, c in counter.items() if c >= threshold}


def _is_brand_text(text: str) -> bool:
    return any(h in text.lower() for h in BRAND_TEXT_HINTS)


def layout_brand(prs) -> list:
    """扫描版式/母版层的品牌残留：模板级 logo 图片 + 品牌文字。

    这些元素定义在版式层，会被所有使用该版式的页继承（所以「不止一页都有」）。
    判定 logo：同一张图出现在 ≥2 个版式，或在母版里（母版图片永远是装饰/品牌）。
    内容图片属于幻灯片层，不在这里处理（由正文图片锚点逻辑接管）。
    """
    items, pics = [], []
    scopes = list(prs.slide_layouts) + [prs.slide_master]
    for lay in scopes:
        for sh in lay.shapes:
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    h = hashlib.md5(sh.image.blob).hexdigest()[:12]
                except Exception:
                    h = ""
                pics.append((lay, h))
    cnt = Counter(h for _, h in pics if h)
    for lay, h in pics:
        if lay is prs.slide_master or (h and cnt[h] >= 2):
            items.append((lay.name, "picture", ""))
    for lay in scopes:
        for sh in lay.shapes:
            if getattr(sh, "has_text_frame", False) and not sh.is_placeholder \
                    and _is_brand_text(sh.text_frame.text):
                items.append((lay.name, "text", sh.text_frame.text.strip()[:24]))
    return items


def strip_brand(prs, notes: list) -> None:
    """从版式/母版删除模板级 logo 图片与品牌文字。"""
    scopes = list(prs.slide_layouts) + [prs.slide_master]
    pics = []
    for lay in scopes:
        for sh in lay.shapes:
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    h = hashlib.md5(sh.image.blob).hexdigest()[:12]
                except Exception:
                    h = ""
                pics.append((lay, sh, h))
    cnt = Counter(h for _, _, h in pics if h)
    for lay, sh, h in pics:
        if lay is prs.slide_master or (h and cnt[h] >= 2):
            blip = sh._element.find(".//" + qn("a:blip"))
            if blip is not None:
                r_id = blip.get(qn("r:embed"))
                if r_id:
                    try:
                        lay.part.drop_rel(r_id)
                    except Exception:
                        pass
            sh._element.getparent().remove(sh._element)
            notes.append(f"已从版式「{lay.name}」移除 logo 图片")
    for lay in scopes:
        for sh in list(lay.shapes):
            if getattr(sh, "has_text_frame", False) and not sh.is_placeholder \
                    and _is_brand_text(sh.text_frame.text):
                t = sh.text_frame.text.strip()[:20]
                sh._element.getparent().remove(sh._element)
                notes.append(f"已从版式「{lay.name}」移除品牌文字「{t}」")


def scrub_examples(prs, notes: list) -> None:
    """清空未被打 token 的残留示例字（封面落款/页脚日期等脚手架文字）。

    只清包含 SCRUB_HINTS 且未含 {{ 的文本框，保留框位置，避免示例字漏进成品。
    """
    cleared = 0
    for slide in prs.slides:
        for sh, _ in walk(slide.shapes):
            if not getattr(sh, "has_text_frame", False):
                continue
            t = sh.text_frame.text
            if "{{" in t:
                continue
            if t.strip() and any(h in t for h in SCRUB_HINTS):
                sh.text_frame.text = ""
                cleared += 1
    if cleared:
        notes.append(f"已清空 {cleared} 处残留示例字（封面落款/页脚日期等）")


def label_slide_types(prs, notes: list) -> None:
    """用原文给每页打页型标签，写进幻灯片备注（PPT_LAYOUT_TYPE:xxx）。

    必须在 token 替换之前调用：引擎分类依赖「目录/CONTENTS」这类文字线索，
    标题换成 {{title}} 之后就没了。
    """
    from app.application.ppt.ppt_engine import _classify_slide, _slide_elements
    slides = list(prs.slides)
    total = len(slides)
    counts = Counter()
    for idx, slide in enumerate(slides):
        try:
            els = _slide_elements(slide, prs.slide_width, prs.slide_height)
            dtype = _classify_slide(els, idx, total)
        except Exception:
            continue
        counts[dtype] += 1
        try:
            tf = slide.notes_slide.notes_text_frame
            existing = tf.text or ""
            marker = f"PPT_LAYOUT_TYPE:{dtype}"
            if marker not in existing:
                tf.text = (existing + "\n" if existing.strip() else "") + marker
        except Exception:
            continue
    if counts:
        notes.append("页型标签已写入备注：" +
                     "、".join(f"{k}×{v}" for k, v in sorted(counts.items())))


def process(prs, notes: list, *, title_tokens: bool = True, point_tokens: bool = True,
            image_anchors: bool = True, image_pages=frozenset(), strip_pictures: bool = False,
            font: str | None = DEFAULT_FONT) -> None:
    """逐页打 token（先图锚点后文字锚点），并统一 run 级字体。"""
    repeated = repeated_picture_hashes(prs)
    if repeated:
        notes.append(f"有 {len(repeated)} 张图片出现在 ≥60% 页面，按装饰处理，不做图片锚点")

    for i, slide in enumerate(prs.slides, 1):
        if image_anchors:
            pics = [(sh, d) for sh, d in walk(slide.shapes)
                    if is_picture(sh) and d == 0]
            target = None
            if image_pages and i in image_pages and pics:
                target = max(pics, key=lambda t: (t[0].width or 0) * (t[0].height or 0))[0]
            elif len(pics) == 1:
                target = pics[0][0]
            if target is not None:
                if pic_hash(target) in repeated:
                    notes.append(f"第 {i} 页 图片在多数页重复，判为装饰，跳过锚点")
                else:
                    left, top = target.left, target.top
                    width, height = target.width, target.height
                    target._element.getparent().remove(target._element)
                    box = slide.shapes.add_textbox(left, top, width, height)
                    box.text_frame.text = "{{image}}"
                    notes.append(f"第 {i} 页 图片位已改为 {{{{image}}}} 锚点")
            elif len(pics) > 1:
                notes.append(f"第 {i} 页有 {len(pics)} 张图，未自动锚定；"
                             "多图页请在 CLI 用 --image-pages 指定")

        if strip_pictures and i > 1:
            # 真实旧稿改模板：未锚定的图片是原稿内容（照片/截图）而非装饰，
            # 复用时会把旧内容带进成品。封面图保留（多为背景设计）。
            victims = [sh for sh, d in walk(slide.shapes)
                       if d == 0 and is_picture(sh)]
            if victims:
                for sh in victims:
                    sh._element.getparent().remove(sh._element)
                notes.append(f"第 {i} 页 已清除未锚定图片 {len(victims)} 张（strip-pictures）")

        if not title_tokens:
            continue
        pw, ph = prs.slide_width, prs.slide_height
        texts = []
        tiny = 0
        for sh, d in walk(slide.shapes):
            if not getattr(sh, "has_text_frame", False):
                continue
            t = sh.text_frame.text.strip()
            if not t or "{{" in t:
                continue
            # 序号/徽章类过小文本框（数字圆点等）是装饰，不插 token，保留原字
            try:
                if sh.width < pw * 0.05 or sh.height < ph * 0.03:
                    tiny += 1
                    continue
            except Exception:
                pass
            texts.append((sh, text_size(sh)))
        if tiny:
            notes.append(f"第 {i} 页有 {tiny} 个过小文本框（序号/徽章类），保留原文不插 token")
        if not texts:
            continue
        texts.sort(key=lambda t: -t[1])
        set_text(texts[0][0], "{{title}}")
        rest = sorted(texts[1:], key=lambda t: (t[0].top or 0, t[0].left or 0))
        if i == 1:
            # 封面上的「在此输入您的党组织名称」类提示框是模板留给单位名称的
            # 位置，是 {{subtitle}} 的最佳归宿；其余封面前缀/示例框（“20XX 基层
            # 党委党支部”这类标题拆段）只对短标题设计，长标题塞进去会与 {{title}}
            # 大字框互相挤占（副标题横在标题旁边、胶囊空着），统一清空。
            hint = next((sh for sh, _ in
                         sorted(rest, key=lambda t: (t[0].top or 0, t[0].left or 0))
                         if any(h in sh.text_frame.text for h in SCRUB_HINTS)), None)
            if hint is not None:
                set_text(hint, "{{subtitle}}")
                notes.append("第 1 页 输入提示框已作为 {{subtitle}}（单位名称）槽位")
                for sh, _ in rest:
                    if sh is not hint:
                        sample = sh.text_frame.text.strip()[:12]
                        set_text(sh, "")
                        notes.append(f"第 1 页 封面前缀框「{sample}」已清空，"
                                     "标题由 {{title}} 槽完整承载")
            elif rest:
                set_text(rest[0][0], "{{subtitle}}")
                for sh, _ in rest[1:]:
                    notes.append(f"第 1 页封面还有文本「{sh.text_frame.text.strip()[:12]}」未处理，"
                                 "请人工确认是单位落款还是残留示例字")
            continue
        if not point_tokens:
            continue
        for idx, (sh, _) in enumerate(rest, 1):
            set_text(sh, "{{point%d}}" % idx)

    if font:
        count = 0
        for slide in prs.slides:
            for sh, _ in walk(slide.shapes):
                if not getattr(sh, "has_text_frame", False):
                    continue
                for para in sh.text_frame.paragraphs:
                    for run in para.runs:
                        # latin / ea / cs 三处同字体 + 去斜体：只改 latin 时
                        # 中文仍继承模板宋体，数字仍是斜体外文字体。
                        apply_cjk_font(run, font)
                        count += 1
        notes.append(f"已统一 {count} 处文本字体为「{font}」")


def _patch_font_blocks(xml: str, font: str, latin: str = DEFAULT_LATIN_FONT):
    """改写 theme 里 majorFont/minorFont 的 latin 与 ea 字体。

    系统读模板字体读的是主题（ppt/theme/themeN.xml），只改 run 级字体不生效：
    学习到的 font 仍是旧值，新增图表等元素的字体也会沿用旧值。latin 与 ea 必须
    分开写，否则主题里的西文也被写成中文字体名，Windows 端会缺字回退。
    """
    total = 0

    def patch_body(body: str) -> str:
        nonlocal total
        new_body, n1 = re.subn(r'<a:latin typeface="[^"]*"',
                               '<a:latin typeface="%s"' % latin, body)
        new_body, n2 = re.subn(r'<a:ea typeface="[^"]*"',
                               '<a:ea typeface="%s"' % font, new_body)
        new_body, n3 = re.subn(r'<a:cs typeface="[^"]*"',
                               '<a:cs typeface="%s"' % font, new_body)
        if n2 == 0 and n1:
            new_body = re.sub(r'(<a:latin typeface="[^"]*"/>)',
                              r'\1<a:ea typeface="%s"/>' % font, new_body, count=1)
        total += n1 + n3 + max(n2, 1 if n1 else 0)
        return new_body

    for tag in ("majorFont", "minorFont"):
        pattern = re.compile(r"(<a:%s>)(.*?)(</a:%s>)" % (tag, tag), re.S)
        xml = pattern.sub(lambda m: m.group(1) + patch_body(m.group(2)) + m.group(3), xml)
    return xml, total


def patch_theme_font_bytes(data: bytes, font: str) -> bytes:
    """在 pptx 字节上改主题字体（zip 内改写，python-pptx 不暴露 theme）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, \
            zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if re.match(r"ppt/theme/theme\d+\.xml$", item.filename):
                xml, _ = _patch_font_blocks(content.decode("utf-8"), font)
                content = xml.encode("utf-8")
            zout.writestr(item, content)
    return buf.getvalue()


def prepare_template_bytes(data: bytes, *, font: str | None = DEFAULT_FONT,
                           keep_brand: bool = False, title_tokens: bool = True,
                           point_tokens: bool = True, image_anchors: bool = True,
                           image_pages=frozenset(), drop_pages=frozenset(),
                           auto_drop: bool = True, scrub: bool = True,
                           strip_pictures: bool = False) -> tuple:
    """对 pptx 字节执行完整机械预处理，返回 (处理后字节, 处理记录)。

    比例不是 16:9 时抛 RatioNotSupported（重排必须人工做，不做等比拉伸）；
    文件损坏抛 Presentation 解析异常，由调用方决定报错方式。
    """
    prs = Presentation(io.BytesIO(data))
    ratio = (prs.slide_width or 0) / (prs.slide_height or 1)
    if abs(ratio - TARGET_RATIO) > 0.02:
        raise RatioNotSupported(
            f"页面比例 {ratio:.3f} 不是 16:9，无法自动预处理。"
            "请先在 PowerPoint 里「设计 → 幻灯片大小 → 宽屏 16:9」并重排版面。")

    notes: list = []
    # 先打页型标签（用原文），再做 token 替换；顺序不能反。
    label_slide_types(prs, notes)
    # 先处理再删页：drop_pages / image_pages 里的页码都按原始页码算。
    process(prs, notes, title_tokens=title_tokens, point_tokens=point_tokens,
            image_anchors=image_anchors, image_pages=image_pages,
            strip_pictures=strip_pictures, font=font)

    if not keep_brand:
        strip_brand(prs, notes)
    if scrub:
        scrub_examples(prs, notes)

    for page in sorted(drop_pages, reverse=True):
        if 1 <= page <= len(prs.slides):
            delete_slide(prs, page - 1)
            notes.append(f"已删除第 {page} 页")

    if auto_drop:
        # 自动删除处理完仍无任何 token/图片锚点的空页（如结束页艺术字、纯装饰页）。
        # 倒序删除，避免索引漂移。
        for idx in range(len(prs.slides) - 1, -1, -1):
            slide = prs.slides[idx]
            has_token = has_pic = False
            for sh, _ in walk(slide.shapes):
                if getattr(sh, "has_text_frame", False) and "{{" in sh.text_frame.text:
                    has_token = True
                if is_picture(sh):
                    has_pic = True
            if not has_token and not has_pic:
                delete_slide(prs, idx)
                notes.append(f"已自动删除空页（原第 {idx + 1} 页，无 token/图片）")

    buf = io.BytesIO()
    prs.save(buf)
    out = buf.getvalue()
    if font:
        out = patch_theme_font_bytes(out, font)
        notes.append(f"主题字体已改写为「{font}」")
    return out, notes
