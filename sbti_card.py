# -*- coding: utf-8 -*-
"""基于 Pillow 生成 SBTI 身份卡片：左 1 / 右 2，仅配图 + 解读；支持外部贴图合成。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

Color = Tuple[int, int, int]

TEXT_FONT_SIZE = 19


def _hex(c: str) -> Color:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _pick_cjk_font_regular() -> Optional[str]:
    """优先常规体，避免黑体加粗。"""
    paths = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\msyhbd.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ]
    for p in paths:
        if Path(p).is_file():
            return p
    return None


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _pick_cjk_font_regular()
    if path:
        try:
            return ImageFont.truetype(path, size=size, index=0)
        except OSError:
            pass
    return ImageFont.load_default()


def _lanczos():
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS


def _wrap_by_pixel_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_w: int,
) -> List[str]:
    lines: List[str] = []
    for para in text.replace("\r", "").split("\n"):
        if not para:
            lines.append("")
            continue
        line = ""
        for ch in para:
            test = line + ch
            bbox = draw.textbbox((0, 0), test, font=font)
            w = bbox[2] - bbox[0]
            if w <= max_w or not line:
                line = test
            else:
                lines.append(line)
                line = ch
        if line:
            lines.append(line)
    return lines


def _lines_height(
    draw: ImageDraw.ImageDraw,
    lines: List[str],
    font: ImageFont.ImageFont,
    line_gap: int,
) -> int:
    h = 0
    for i, line in enumerate(lines):
        ref = line if line else " "
        bbox = draw.textbbox((0, 0), ref, font=font)
        lh = bbox[3] - bbox[1]
        h += lh + (line_gap if i < len(lines) - 1 else 0)
    return h


def render_identity_card_base(
    result: Dict[str, Any],
    poster_path: Optional[Path],
    total_width: int = 1200,
) -> Image.Image:
    """
    渲染无贴图的底图：左 1 / 右 2，左侧配图 + 右侧 desc（常规小字号）。
    """
    bg = _hex("#f2f7f3")
    fg_text = _hex("#304034")
    fg_muted = _hex("#6a786f")
    line_c = _hex("#dbe8dd")
    slot_bg = _hex("#edf6ef")

    t = result["final_type"]
    desc = (t.get("desc") or "").strip()

    left_w = total_width // 3
    right_w = total_width - left_w
    pad = 32

    f_main = _font(TEXT_FONT_SIZE)

    dummy = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    text_inner_w = right_w - 2 * pad
    lines = _wrap_by_pixel_width(
        dummy, desc if desc else "（暂无解读）", f_main, text_inner_w
    )
    line_gap = 10
    text_h = _lines_height(dummy, lines, f_main, line_gap)

    inner_h_cap = 1600
    thumb: Optional[Image.Image] = None
    if poster_path and poster_path.is_file():
        try:
            thumb = Image.open(poster_path).convert("RGBA")
            tw = max(1, left_w - 2 * pad)
            thumb.thumbnail((tw, inner_h_cap), _lanczos())
        except OSError:
            thumb = None

    ih = thumb.height if thumb else 220
    H = max(text_h + 2 * pad, ih + 2 * pad, 480)

    if thumb:
        tw = max(1, left_w - 2 * pad)
        th_max = max(1, H - 2 * pad)
        t2 = thumb.copy()
        t2.thumbnail((tw, th_max), _lanczos())
        thumb = t2
        ih = thumb.height

    img = Image.new("RGB", (total_width, H), bg)
    draw = ImageDraw.Draw(img)

    draw.line([(left_w, 0), (left_w, H)], fill=line_c, width=2)

    if thumb:
        ix = (left_w - thumb.width) // 2
        iy = (H - thumb.height) // 2
        if iy < pad:
            iy = pad
        if thumb.mode == "RGBA":
            img.paste(thumb, (ix, iy), thumb)
        else:
            img.paste(thumb, (ix, iy))
    else:
        box = [pad, (H - 220) // 2, left_w - pad, (H - 220) // 2 + 220]
        try:
            draw.rounded_rectangle(box, radius=16, fill=slot_bg, outline=line_c)
        except AttributeError:
            draw.rectangle(box, fill=slot_bg, outline=line_c)
        hint = "（无配图）"
        bbox = draw.textbbox((0, 0), hint, font=_font(18))
        tw0 = bbox[2] - bbox[0]
        th0 = bbox[3] - bbox[1]
        draw.text(
            ((left_w - tw0) // 2, (H - th0) // 2),
            hint,
            font=_font(18),
            fill=fg_muted,
        )

    tx = left_w + pad
    ty = pad
    for i, line in enumerate(lines):
        draw.text((tx, ty), line, font=f_main, fill=fg_text)
        ref = line if line else " "
        bbox = draw.textbbox((0, 0), ref, font=f_main)
        ty += bbox[3] - bbox[1] + (line_gap if i < len(lines) - 1 else 0)

    return img


def composite_sticker(
    base: Image.Image,
    sticker: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
) -> Image.Image:
    """在底图上粘贴贴图（缩放到 w×h，支持 RGBA，左上角对齐）。"""
    out = base.copy()
    st = sticker.convert("RGBA").resize((max(1, w), max(1, h)), _lanczos())
    out.paste(st, (int(x), int(y)), st)
    return out.convert("RGB")


def composite_sticker_transformed(
    base: Image.Image,
    sticker: Image.Image,
    center_x: float,
    center_y: float,
    w: int,
    h: int,
    angle_deg: float,
) -> Image.Image:
    """
    以 (center_x, center_y) 为中心粘贴贴图：先缩放到 w×h，再按角度旋转（expand），再对齐中心。
    angle_deg 与 Pillow rotate 一致：正值为逆时针。
    """
    try:
        rot_resample = Image.Resampling.BICUBIC
    except AttributeError:
        rot_resample = Image.BICUBIC
    st = sticker.convert("RGBA").resize((max(1, w), max(1, h)), _lanczos())
    st = st.rotate(
        float(angle_deg),
        expand=True,
        resample=rot_resample,
        fillcolor=(0, 0, 0, 0),
    )
    out = base.copy().convert("RGBA")
    left = int(round(center_x - st.width / 2.0))
    top = int(round(center_y - st.height / 2.0))
    out.paste(st, (left, top), st)
    return out.convert("RGB")


def generate_identity_card(
    result: Dict[str, Any],
    *,
    poster_path: Optional[Path],
    out_path: Path,
    total_width: int = 1200,
) -> None:
    img = render_identity_card_base(result, poster_path, total_width=total_width)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG", optimize=True)
