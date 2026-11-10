"""把一套 PPTX 模板整体换主色，版式/图位/页型一个不动。

用途：同一套设计语言出多个配色变体（红 → 蓝 / 绿 / 金），不必为每个颜色
重新找模板。页型齐全的模板很少（本地 28 套里只有一套 cover/toc/section/
content/data/closing 全都有），重买模板不如直接换色。

两条通道，缺一不可：
- XML 里的 srgbClr 直接文本替换（主色高度集中，实测一套 35 页模板里
  主红出现 202 次、米白底 135 次，替换这两条就覆盖 95%）
- 装饰是 PNG 线描图，按色相整体旋转（红 0° → 目标色 hue），降饱和像素
  （白底、灰线）不参与，避免整张泛蓝

用法：
    python deploy/recolor_ppt_template.py \
        --src "ppttem/_processed/原模板_处理后.pptx" \
        --dst "ppttem/_processed/原模板_蓝色版.pptx" \
        --to-primary 1F5FAA

换完还要让系统认识它：管理端重新上传 dst，或跑 analyze_template 脚本入库。
"""
import argparse
import colorsys
import io
import os
import re
import sys
import zipfile

import numpy as np
from PIL import Image

# 原模板的辅助色 → 新配色里的对应色。表里没有的颜色原样保留。
BASE_PAIRS = {
    "C00000": "primary",
    "7C4939": "dark",
    "FFFAF0": "paper",
    "F8F0DC": "paper_alt",
    "FAEDED": "tint",
}
EXTRA = {
    "F26B43": "accent",
    "E6DBC4": "paper_alt",
    "63170E": "dark_deep",
    "361818": "text_dark",
}


def hex_to_rgb(value: str):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb) -> str:
    return "".join(f"{max(0, min(255, int(round(c)))):02X}" for c in rgb)


def mix_white(rgb, ratio: float):
    return tuple(c + (255 - c) * ratio for c in rgb)


def darken(rgb, ratio: float = .45):
    return tuple(c * (1 - ratio) for c in rgb)


def build_palette(primary_hex: str, paper_hex: str) -> dict:
    primary = hex_to_rgb(primary_hex)
    paper = hex_to_rgb(paper_hex)
    return {
        "primary": primary_hex.upper(),
        "dark": rgb_to_hex(darken(primary, .35)),
        "paper": paper_hex.upper(),
        "paper_alt": rgb_to_hex(mix_white(paper, .08)),
        "tint": rgb_to_hex(mix_white(paper, .02)),
        "accent": rgb_to_hex(mix_white(primary, .28)),
        "dark_deep": rgb_to_hex(darken(primary, .55)),
        "text_dark": rgb_to_hex(darken(primary, .62)),
    }


def hue_of(rgb) -> float:
    return colorsys.rgb_to_hsv(*[c / 255 for c in rgb])[0] * 255


def recolor_pixels(blob: bytes, shift: int) -> bytes:
    """线描 PNG 整体色相旋转；无彩像素不动，只搬有饱和度的笔画。"""
    image = Image.open(io.BytesIO(blob))
    alpha = image.convert("RGBA").getchannel("A")
    hsv = np.array(image.convert("RGB").convert("HSV")).astype(np.int16)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    colored = sat > 18
    hue[colored] = (hue[colored] + shift) % 256
    merged = np.stack([hue, sat, val], axis=-1).astype("uint8")
    out = Image.fromarray(merged, "HSV").convert("RGBA")
    out.putalpha(alpha)
    buffer = io.BytesIO()
    out.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--dst", required=True)
    parser.add_argument("--from-primary", default="C00000",
                        help="原模板主色，默认 C00000")
    parser.add_argument("--to-primary", default="1F5FAA",
                        help="目标主色，默认政务蓝 1F5FAA")
    parser.add_argument("--paper", default=None,
                        help="目标纸白底，默认由主色混白推导")
    args = parser.parse_args()

    if not os.path.isfile(args.src):
        sys.exit(f"源文件不存在：{args.src}")

    target = hex_to_rgb(args.to_primary)
    paper = args.paper or rgb_to_hex(mix_white(target, .965))
    palette = build_palette(args.to_primary, paper)

    mapping = {}
    pairs = dict(BASE_PAIRS)
    pairs.update({k: v for k, v in EXTRA.items() if v in palette})
    pairs[args.from_primary.upper()] = "primary"
    for source_hex, role in pairs.items():
        if role in palette:
            mapping[source_hex.upper()] = palette[role]

    shift = int(round((hue_of(target) - hue_of(hex_to_rgb(args.from_primary))) % 256))

    images = xmls = 0
    os.makedirs(os.path.dirname(os.path.abspath(args.dst)), exist_ok=True)
    with zipfile.ZipFile(args.src) as source, \
            zipfile.ZipFile(args.dst, "w", zipfile.ZIP_DEFLATED) as out:
        for item in source.infolist():
            data = source.read(item.filename)
            name = item.filename.lower()
            if name.startswith("ppt/media/") and name.endswith((".png", ".jpg", ".jpeg")):
                try:
                    data = recolor_pixels(data, shift)
                    images += 1
                except Exception as exc:
                    print(f"  图片跳过 {item.filename}: {exc}")
            elif name.startswith("ppt/") and name.endswith(".xml"):
                text = data.decode("utf-8", "ignore")
                new = text
                for old, new_hex in mapping.items():
                    new = re.sub(rf'(srgbClr val="){old}(")', rf'\g<1>{new_hex}\g<2>',
                                 new, flags=re.IGNORECASE)
                    new = re.sub(rf'(val="){old}(")', rf'\g<1>{new_hex}\g<2>',
                                 new, flags=re.IGNORECASE)
                if new != text:
                    xmls += 1
                data = new.encode("utf-8")
            out.writestr(item, data)

    print(f"输出 {args.dst}")
    print(f"主色 {args.from_primary} → {args.to_primary}，色相位移 {shift}")
    print(f"配色表 {palette}")
    print(f"图片重上色 {images} 张，XML 改色 {xmls} 个")


if __name__ == "__main__":
    main()
