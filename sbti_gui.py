# -*- coding: utf-8 -*-
"""
SBTI 人格测试 — 桌面 GUI（CustomTkinter）。
题库与判分与 sbti_quiz.py、index.html 一致；结果配图读取项目目录下 image/ 文件夹。
"""

from __future__ import annotations

import math
import random
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import customtkinter as ctk
from PIL import Image, ImageTk

from sbti_card import (
    composite_sticker_transformed,
    render_identity_card_base,
)

from sbti_quiz import (
    compute_result,
    DIMENSION_META,
    DIM_EXPLANATIONS,
    format_user_lm_pattern,
    QUESTIONS,
    SPECIAL_QUESTIONS,
    TYPE_IMAGES,
)

def _app_base_dir() -> Path:
    """源码运行用脚本目录；PyInstaller 单文件 exe 用临时解压目录。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


BASE_DIR = _app_base_dir()

# 与网页一致的浅绿主题
COLOR_BG = "#f2f7f3"
COLOR_CARD = "#ffffff"
COLOR_ACCENT = "#4d6a53"
COLOR_ACCENT_SOFT = "#6c8d71"
COLOR_MUTED = "#6a786f"
COLOR_LINE = "#dbe8dd"

# 与 sbti_quiz 中 dimensionOrder 分组一致，用于结果页展示
DIMENSION_MODEL_GROUPS: List[tuple[str, List[str]]] = [
    ("自我模型（S1–S3）", ["S1", "S2", "S3"]),
    ("情感模型（E1–E3）", ["E1", "E2", "E3"]),
    ("态度模型（A1–A3）", ["A1", "A2", "A3"]),
    ("行动驱力（Ac1–Ac3）", ["Ac1", "Ac2", "Ac3"]),
    ("社交模型（So1–So3）", ["So1", "So2", "So3"]),
]


def shuffle_questions(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    arr = list(items)
    for i in range(len(arr) - 1, 0, -1):
        j = random.randint(0, i)
        arr[i], arr[j] = arr[j], arr[i]
    return arr


def get_visible_questions(
    shuffled: List[Dict[str, Any]], answers: Dict[str, Any]
) -> List[Dict[str, Any]]:
    visible = list(shuffled)
    gate_idx = next(
        (i for i, q in enumerate(visible) if q["id"] == "drink_gate_q1"), -1
    )
    if gate_idx != -1 and answers.get("drink_gate_q1") == 3:
        gate2 = SPECIAL_QUESTIONS[1]
        visible = visible[: gate_idx + 1] + [gate2] + visible[gate_idx + 1 :]
    return visible


def resolve_type_image_path(type_code: str) -> Optional[Path]:
    rel = TYPE_IMAGES.get(type_code)
    if not rel:
        return None
    # pathlib 在 Windows 上也能识别正斜杠；勿用 Path.sep（Path 类型没有该属性）
    path = (BASE_DIR / rel.lstrip("./")).resolve()
    if path.is_file():
        return path
    return None


def _pillow_lanczos():
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS


def _rot_local(lx: float, ly: float, ang_deg: float) -> Tuple[float, float]:
    r = math.radians(ang_deg)
    c, s = math.cos(r), math.sin(r)
    return lx * c - ly * s, lx * s + ly * c


class ExportCardChoiceDialog(ctk.CTkToplevel):
    """二选一：直接导出底图，或打开贴图编辑器。"""

    def __init__(self, master: ctk.CTk) -> None:
        super().__init__(master)
        self.title("导出身份卡片")
        self.geometry("420x200")
        self.resizable(False, False)
        self.transient(master)
        self.choice: Optional[str] = None

        box = ctk.CTkFrame(self, fg_color="transparent")
        box.pack(expand=True, fill="both", padx=24, pady=24)

        ctk.CTkLabel(
            box,
            text="请选择导出方式",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#1e2a22",
        ).pack(pady=(0, 16))

        ctk.CTkButton(
            box,
            text="直接导出（仅底图：左图右文）",
            height=44,
            fg_color=COLOR_ACCENT,
            hover_color="#3d5642",
            command=lambda: self._pick("direct"),
        ).pack(fill="x", pady=6)

        ctk.CTkButton(
            box,
            text="添加我的照片（编辑器里拖动、缩放、旋转）",
            height=44,
            fg_color=COLOR_ACCENT_SOFT,
            hover_color="#5a7a5f",
            command=lambda: self._pick("edit"),
        ).pack(fill="x", pady=6)

        ctk.CTkButton(box, text="取消", height=36, command=self.destroy).pack(
            pady=(12, 0)
        )

    def _pick(self, v: str) -> None:
        self.choice = v
        self.destroy()


class CardStickerEditor(ctk.CTkToplevel):
    """底图 + 贴图：拖拽平移；四角等比缩放；顶边延长线末端旋转。"""

    HANDLE_HIT = 11
    ROT_HIT = 13

    def __init__(
        self,
        master: ctk.CTk,
        result: Dict[str, Any],
        poster_path: Optional[Path],
    ) -> None:
        super().__init__(master)
        self.title("身份卡片 · 贴图编辑")
        self.geometry("960x780")
        self.minsize(800, 640)
        self.transient(master)

        self._result = result
        self.base_pil = render_identity_card_base(result, poster_path)
        self.bw, self.bh = self.base_pil.size
        self.ps = min(900 / self.bw, 620 / self.bh)

        self.sticker_orig: Optional[Image.Image] = None
        self._ar = 1.0
        self.st_cx = self.bw / 2.0
        self.st_cy = self.bh / 2.0
        self.st_w = 120.0
        self.st_h = 120.0
        self.st_angle = 0.0

        self._mode: Optional[Tuple[Any, ...]] = None
        self._photo_bg: Optional[ImageTk.PhotoImage] = None
        self._photo_st: Optional[ImageTk.PhotoImage] = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        hint = ctk.CTkLabel(
            self,
            text="先选照片 | 拖中间平移 | 拖四角等比缩放 | 拖上方圆点旋转",
            font=ctk.CTkFont(size=13),
            text_color=COLOR_MUTED,
        )
        hint.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))

        c_fr = ctk.CTkFrame(self, fg_color="#c8d0cc")
        c_fr.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        c_fr.grid_rowconfigure(0, weight=1)
        c_fr.grid_columnconfigure(0, weight=1)

        cw = max(1, int(self.bw * self.ps))
        ch = max(1, int(self.bh * self.ps))
        self.canvas = tk.Canvas(
            c_fr, width=cw, height=ch, highlightthickness=0, bg="#b0b8b4"
        )
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

        base_prev = self.base_pil.resize((cw, ch), _pillow_lanczos())
        self._photo_bg = ImageTk.PhotoImage(base_prev)
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo_bg)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.grid(row=2, column=0, sticky="ew", padx=12, pady=10)

        ctk.CTkButton(
            ctrl, text="选择我的照片…", width=140, command=self._pick_sticker
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            ctrl,
            text="导出 PNG",
            width=120,
            fg_color=COLOR_ACCENT,
            hover_color="#3d5642",
            command=self._export_png,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(ctrl, text="关闭", width=80, command=self.destroy).pack(
            side="right"
        )

    def _corners_image(self) -> List[Tuple[float, float]]:
        hw, hh = self.st_w / 2.0, self.st_h / 2.0
        locs = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
        out: List[Tuple[float, float]] = []
        for lx, ly in locs:
            wx, wy = _rot_local(lx, ly, self.st_angle)
            out.append((self.st_cx + wx, self.st_cy + wy))
        return out

    def _rotation_axis_image(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """顶边中点 → 沿外法线延伸得到旋转控制点（图像坐标）。"""
        hh = self.st_h / 2.0
        tx, ty = _rot_local(0.0, -hh, self.st_angle)
        tmx, tmy = self.st_cx + tx, self.st_cy + ty
        ox, oy = _rot_local(0.0, -1.0, self.st_angle)
        L = max(48.0, 0.12 * math.hypot(self.st_w, self.st_h))
        n = math.hypot(ox, oy) or 1.0
        ox, oy = ox / n, oy / n
        rhx = tmx + ox * L
        rhy = tmy + oy * L
        return (tmx, tmy), (rhx, rhy)

    def _hit_test(self, e: tk.Event) -> Optional[Tuple[Any, ...]]:
        if not self.sticker_orig:
            return None
        _, rh = self._rotation_axis_image()
        rcx, rcy = rh[0] * self.ps, rh[1] * self.ps
        if math.hypot(e.x - rcx, e.y - rcy) < self.ROT_HIT:
            return ("rot",)
        for i, (ix, iy) in enumerate(self._corners_image()):
            cx, cy = ix * self.ps, iy * self.ps
            if math.hypot(e.x - cx, e.y - cy) < self.HANDLE_HIT:
                return ("resize", i)
        fx, fy = e.x / self.ps, e.y / self.ps
        lx, ly = self._local_inv(fx, fy)
        if abs(lx) <= self.st_w / 2 and abs(ly) <= self.st_h / 2:
            return ("pan",)
        return None

    def _local_inv(self, fx: float, fy: float) -> Tuple[float, float]:
        dx, dy = fx - self.st_cx, fy - self.st_cy
        return _rot_local(dx, dy, -self.st_angle)

    def _redraw_sticker(self) -> None:
        self.canvas.delete("sticker_layer")
        if not self.sticker_orig:
            self._photo_st = None
            return
        w = max(1, int(self.st_w * self.ps))
        h = max(1, int(self.st_h * self.ps))
        st = self.sticker_orig.resize((w, h), _pillow_lanczos())
        try:
            rmode = Image.Resampling.BICUBIC
        except AttributeError:
            rmode = Image.BICUBIC
        st = st.rotate(
            float(self.st_angle),
            expand=True,
            resample=rmode,
            fillcolor=(0, 0, 0, 0),
        )
        self._photo_st = ImageTk.PhotoImage(st)
        cxc, cyc = self.st_cx * self.ps, self.st_cy * self.ps
        ox = cxc - st.width / 2.0
        oy = cyc - st.height / 2.0
        self.canvas.create_image(
            ox, oy, anchor="nw", image=self._photo_st, tags="sticker_layer"
        )
        for i, (ix, iy) in enumerate(self._corners_image()):
            cx, cy = ix * self.ps, iy * self.ps
            self.canvas.create_rectangle(
                cx - 5,
                cy - 5,
                cx + 5,
                cy + 5,
                fill="white",
                outline=COLOR_ACCENT,
                width=2,
                tags="sticker_layer",
            )
        tmid, rh = self._rotation_axis_image()
        tx, ty = tmid[0] * self.ps, tmid[1] * self.ps
        rx, ry = rh[0] * self.ps, rh[1] * self.ps
        self.canvas.create_line(
            tx, ty, rx, ry, fill=COLOR_ACCENT, width=2, tags="sticker_layer"
        )
        self.canvas.create_oval(
            rx - 7,
            ry - 7,
            rx + 7,
            ry + 7,
            fill="white",
            outline=COLOR_ACCENT,
            width=2,
            tags="sticker_layer",
        )

    def _pick_sticker(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="选择贴图图片",
            filetypes=[
                ("图片", "*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp"),
                ("全部", "*.*"),
            ],
        )
        if not path:
            return
        try:
            im = Image.open(path).convert("RGBA")
        except OSError as err:
            messagebox.showerror("无法打开图片", str(err), parent=self)
            return
        self.sticker_orig = im
        ow, oh = im.size
        self._ar = (ow / oh) if oh else 1.0
        self.st_cx = self.bw / 2.0
        self.st_cy = self.bh / 2.0
        self.st_w = float(max(24, int(self.bw * 0.22)))
        self.st_h = float(max(24, int(self.st_w / self._ar)))
        self.st_angle = 0.0
        self._redraw_sticker()

    def _on_press(self, e: tk.Event) -> None:
        self._mode = self._hit_test(e)
        if self._mode == ("rot",):
            cxc = self.st_cx * self.ps
            cyc = self.st_cy * self.ps
            self._rot_start_angle = self.st_angle
            # 画布 y 向下，与 atan2 默认的数学坐标（y 向上）相反，需对 y 取反
            self._rot_mouse0 = math.degrees(math.atan2(cyc - e.y, e.x - cxc))
        elif self._mode and self._mode[0] == "resize":
            idx = self._mode[1]
            corners = self._corners_image()
            cox, coy = corners[idx]
            self._rs_vx = cox - self.st_cx
            self._rs_vy = coy - self.st_cy
            self._rs_vlen = math.hypot(self._rs_vx, self._rs_vy) or 1e-6
            self._rs_w0 = self.st_w
        elif self._mode == ("pan",):
            self._pan_mx, self._pan_my = float(e.x), float(e.y)
            self._pan_cx0, self._pan_cy0 = self.st_cx, self.st_cy

    def _on_drag(self, e: tk.Event) -> None:
        if self._mode == ("rot",):
            cxo = self.st_cx * self.ps
            cyo = self.st_cy * self.ps
            a = math.degrees(math.atan2(cyo - e.y, e.x - cxo))
            self.st_angle = self._rot_start_angle + (a - self._rot_mouse0)
            self._redraw_sticker()
        elif self._mode and self._mode[0] == "resize":
            fx, fy = e.x / self.ps, e.y / self.ps
            wx, wy = fx - self.st_cx, fy - self.st_cy
            t = (wx * self._rs_vx + wy * self._rs_vy) / self._rs_vlen
            scale = max(0.06, t / self._rs_vlen)
            self.st_w = max(16.0, self._rs_w0 * scale)
            self.st_h = max(16.0, self.st_w / self._ar)
            self._redraw_sticker()
        elif self._mode == ("pan",):
            self.st_cx = self._pan_cx0 + (e.x - self._pan_mx) / self.ps
            self.st_cy = self._pan_cy0 + (e.y - self._pan_my) / self.ps
            self._redraw_sticker()

    def _on_release(self, _: tk.Event) -> None:
        self._mode = None

    def _export_png(self) -> None:
        code = self._result["final_type"]["code"]
        safe = "".join(c if c not in '<>:"/\\|?*' else "_" for c in code)
        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png")],
            initialfile=f"SBTI_{safe}.png",
            title="导出身份卡片",
        )
        if not path:
            return
        try:
            if self.sticker_orig:
                out = composite_sticker_transformed(
                    self.base_pil,
                    self.sticker_orig,
                    self.st_cx,
                    self.st_cy,
                    int(round(self.st_w)),
                    int(round(self.st_h)),
                    float(self.st_angle),
                )
            else:
                out = self.base_pil
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            out.save(path, format="PNG", optimize=True)
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self)
            return
        messagebox.showinfo("已保存", path, parent=self)


class SBTIApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SBTI 人格测试")
        self.geometry("1020x760")
        self.minsize(880, 640)

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("green")

        self.configure(fg_color=COLOR_BG)

        self._answers: Dict[str, Any] = {}
        self._shuffled: List[Dict[str, Any]] = []
        self._visible: List[Dict[str, Any]] = []
        self._index = 0
        self._radio_var: Optional[ctk.StringVar] = None
        self._main = ctk.CTkFrame(self, fg_color="transparent")
        self._main.pack(fill="both", expand=True, padx=20, pady=16)

        self._show_intro()

    def _clear_main(self) -> None:
        self._unbind_quiz_shortcuts()
        for w in self._main.winfo_children():
            w.destroy()

    def _unbind_quiz_shortcuts(self) -> None:
        for seq in ("<Return>", "<KP_Enter>", "<KeyPress>"):
            try:
                self.unbind(seq)
            except tk.TclError:
                pass

    def _bind_quiz_shortcuts(self, q: Dict[str, Any]) -> None:
        """键盘 A–E（对应选项 A–E，不区分大小写）；Enter / 小键盘 Enter → 下一题。"""
        n = len(q["options"])

        def on_enter(_: tk.Event) -> None:
            self._next_question()

        def on_key(event: tk.Event) -> Optional[str]:
            keysym = (event.keysym or "").lower()
            if keysym in ("return", "kp_enter"):
                return None
            if keysym in ("a", "b", "c", "d", "e"):
                idx = ord(keysym) - ord("a")
                if 0 <= idx < n and self._radio_var:
                    val = str(int(q["options"][idx]["value"]))
                    self._radio_var.set(val)
                return "break"
            return None

        self.bind("<Return>", on_enter)
        self.bind("<KP_Enter>", on_enter)
        self.bind("<KeyPress>", on_key)

    def _show_intro(self) -> None:
        self._clear_main()

        card = ctk.CTkFrame(
            self._main,
            fg_color=COLOR_CARD,
            corner_radius=20,
            border_width=1,
            border_color=COLOR_LINE,
        )
        card.pack(fill="both", expand=True)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(expand=True, padx=48, pady=48)

        eyebrow = ctk.CTkLabel(
            inner,
            text="  娱乐向人格测试  ·  结果别太当真  ",
            font=ctk.CTkFont(size=13),
            text_color=COLOR_ACCENT,
            fg_color="#edf6ef",
            corner_radius=14,
        )
        eyebrow.pack(pady=(0, 18))

        title = ctk.CTkLabel(
            inner,
            text="MBTI已经过时，\nSBTI来了。",
            font=ctk.CTkFont(size=36, weight="bold"),
            text_color="#1e2a22",
            justify="center",
        )
        title.pack(pady=(0, 28))

        ctk.CTkButton(
            inner,
            text="开始测试",
            font=ctk.CTkFont(size=16, weight="bold"),
            height=48,
            width=200,
            fg_color=COLOR_ACCENT,
            hover_color="#3d5642",
            corner_radius=14,
            command=self._start_quiz,
        ).pack()

        hint = ctk.CTkLabel(
            inner,
            text="题目顺序将随机打乱，不影响最终结果。",
            font=ctk.CTkFont(size=13),
            text_color=COLOR_MUTED,
        )
        hint.pack(pady=(24, 0))

    def _start_quiz(self) -> None:
        self._answers = {}
        regular = shuffle_questions(QUESTIONS)
        insert_at = random.randint(1, len(regular))
        self._shuffled = (
            regular[:insert_at] + [SPECIAL_QUESTIONS[0]] + regular[insert_at:]
        )
        self._sync_visible()
        self._index = 0
        self._show_question()

    def _sync_visible(self) -> None:
        self._visible = get_visible_questions(self._shuffled, self._answers)

    def _current_question(self) -> Optional[Dict[str, Any]]:
        if 0 <= self._index < len(self._visible):
            return self._visible[self._index]
        return None

    def _show_question(self) -> None:
        self._clear_main()
        q = self._current_question()
        if not q:
            self._finish_quiz()
            return

        top = ctk.CTkFrame(self._main, fg_color="transparent")
        top.pack(fill="x", pady=(0, 10))

        done = sum(
            1 for qn in self._visible if self._answers.get(qn["id"]) is not None
        )
        total = len(self._visible)
        pct = done / total if total else 0

        bar_bg = ctk.CTkFrame(top, fg_color="#edf3ee", height=10, corner_radius=8)
        bar_bg.pack(fill="x", pady=(0, 8))
        bar_bg.pack_propagate(False)

        bar_fill = ctk.CTkFrame(
            bar_bg,
            fg_color=COLOR_ACCENT_SOFT,
            corner_radius=8,
            width=max(8, int(bar_bg.winfo_reqwidth() * pct) or int(900 * pct)),
        )
        bar_fill.place(relx=0, rely=0, relheight=1, relwidth=pct or 0.02)

        ctk.CTkLabel(
            top,
            text=f"{self._index + 1} / {total}  ·  已答 {done}/{total}",
            font=ctk.CTkFont(size=13),
            text_color=COLOR_MUTED,
        ).pack(anchor="w")

        card = ctk.CTkFrame(
            self._main,
            fg_color=COLOR_CARD,
            corner_radius=20,
            border_width=1,
            border_color=COLOR_LINE,
        )
        card.pack(fill="both", expand=True)

        body = ctk.CTkScrollableFrame(card, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=22)

        meta = "补充题" if q.get("special") else "维度已隐藏"
        ctk.CTkLabel(
            body,
            text=meta,
            font=ctk.CTkFont(size=12),
            text_color=COLOR_MUTED,
        ).pack(anchor="w", pady=(0, 8))

        ctk.CTkLabel(
            body,
            text=q["text"],
            font=ctk.CTkFont(size=16),
            text_color="#1e2a22",
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(0, 18))

        stored = self._answers.get(q["id"])
        self._radio_var = ctk.StringVar(
            value="" if stored is None else str(int(stored))
        )

        codes = ["A", "B", "C", "D", "E"]
        for i, opt in enumerate(q["options"]):
            code = codes[i] if i < len(codes) else str(i + 1)
            val = str(int(opt["value"]))
            row = ctk.CTkFrame(body, fg_color="#fbfdfb", corner_radius=14)
            row.pack(fill="x", pady=6)

            rb = ctk.CTkRadioButton(
                row,
                text=f"  {code}.  {opt['label']}",
                variable=self._radio_var,
                value=val,
                font=ctk.CTkFont(size=15),
                fg_color=COLOR_ACCENT,
                hover_color=COLOR_ACCENT_SOFT,
                text_color="#1e2a22",
                radiobutton_width=20,
                radiobutton_height=20,
            )
            rb.pack(anchor="w", padx=14, pady=12)

        nav = ctk.CTkFrame(self._main, fg_color="transparent")
        nav.pack(fill="x", pady=(14, 0))

        ctk.CTkButton(
            nav,
            text="上一题",
            width=120,
            height=40,
            fg_color=COLOR_CARD,
            text_color=COLOR_ACCENT,
            border_width=1,
            border_color=COLOR_LINE,
            hover_color="#edf6ef",
            command=self._prev_question,
        ).pack(side="left")

        ctk.CTkButton(
            nav,
            text="返回首页",
            width=120,
            height=40,
            fg_color="transparent",
            text_color=COLOR_MUTED,
            hover_color="#edf3ee",
            command=self._show_intro,
        ).pack(side="left", padx=(12, 0))

        ctk.CTkLabel(
            nav,
            text="快捷键：A B C D E 选对应项 · Enter 下一题",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_MUTED,
        ).pack(side="left", padx=(20, 0))

        next_text = "查看结果" if self._index >= total - 1 else "下一题"
        ctk.CTkButton(
            nav,
            text=next_text,
            width=140,
            height=40,
            fg_color=COLOR_ACCENT,
            hover_color="#3d5642",
            command=self._next_question,
        ).pack(side="right")

        self._bind_progress_hack(bar_bg, bar_fill, pct)

        self._bind_quiz_shortcuts(q)
        self.focus_set()

    def _bind_progress_hack(self, bar_bg: ctk.CTkFrame, bar_fill: ctk.CTkFrame, pct: float) -> None:
        def redraw(_: Any = None) -> None:
            try:
                w = bar_bg.winfo_width()
                if w <= 1:
                    return
                bar_fill.place_forget()
                bar_fill.configure(width=max(8, int(w * pct)))
                bar_fill.place(relx=0, rely=0, relheight=1, relwidth=max(pct, 0.02))
            except Exception:
                pass

        bar_bg.bind("<Configure>", redraw)
        self.after(100, redraw)

    def _prev_question(self) -> None:
        if self._index <= 0:
            return
        self._index -= 1
        self._show_question()

    def _next_question(self) -> None:
        q = self._current_question()
        if not q or self._radio_var is None:
            return
        raw = self._radio_var.get().strip()
        if not raw:
            return
        val = int(raw)
        valid = {int(o["value"]) for o in q["options"]}
        if val not in valid:
            return

        qid = q["id"]
        self._answers[qid] = val

        if qid == "drink_gate_q1" and val != 3:
            self._answers.pop("drink_gate_q2", None)

        self._sync_visible()

        if self._all_answered():
            self._finish_quiz()
            return

        if self._index < len(self._visible) - 1:
            self._index += 1
        self._show_question()

    def _all_answered(self) -> bool:
        self._sync_visible()
        return all(self._answers.get(qn["id"]) is not None for qn in self._visible)

    def _finish_quiz(self) -> None:
        if not self._all_answered():
            self._show_question()
            return
        result = compute_result(self._answers)
        self._show_result(result)

    def _result_section_title(
        self, parent: ctk.CTkScrollableFrame, text: str, *, first: bool = False
    ) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLOR_ACCENT,
            anchor="w",
        ).pack(anchor="w", pady=(6 if first else 18, 6), padx=4)

    def _result_readonly_text(
        self,
        parent: ctk.CTkScrollableFrame,
        text: str,
        *,
        height: int = 120,
    ) -> None:
        tb = ctk.CTkTextbox(
            parent,
            height=height,
            font=ctk.CTkFont(size=14),
            text_color="#304034",
            fg_color="#fbfdfb",
            border_width=1,
            border_color=COLOR_LINE,
            corner_radius=12,
            wrap="word",
        )
        tb.pack(fill="x", pady=(0, 4), padx=4)
        tb.insert("1.0", text)
        tb.configure(state="disabled")

    def _build_tab_comprehensive_analysis(
        self, tab: Any, result: Dict[str, Any]
    ) -> None:
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        levels = result["levels"]
        pattern = format_user_lm_pattern(levels)
        bn = result["best_normal"]

        self._result_section_title(scroll, "十五维档位指纹", first=True)
        raw_lines = [
            f"指纹串（与 25 种标准模板逐位比对时的格式）：\n{pattern}",
            "",
            "字母含义：L=低、M=中、H=高。每一细维度由两题得分相加：≤3→L，=4→M，≥5→H。",
            "",
            "五段依次为：自我（S）· 情感（E）· 态度（A）· 行动驱力（Ac）· 社交（So）。",
        ]
        self._result_readonly_text(scroll, "\n".join(raw_lines), height=170)

        self._result_section_title(scroll, "算法说明（与网页版一致）")
        algo = (
            "1. 将你的档位向量与标准库中 25 个人格模板逐维比较（仅比较 L/M/H，与题干表述无关）。\n"
            "2. 曼哈顿距离：某一维相差 1 个档位计 1 分，15 维累计为 d（理论最大 30）。\n"
            f"3. 相似度 = round((1 − d/30) × 100)。d 越小越优先；相同时「精准命中维数」更多者优先。\n"
            f"4. 当前与标准库第一名「{bn['code']}（{bn['cn']}）」：总距离 {bn['distance']}，"
            f"精准命中 {bn['exact']}/15 维，相似度 {bn['similarity']}%。"
        )
        self._result_readonly_text(scroll, algo, height=150)

        sec = result.get("secondary_type")
        code_final = result["final_type"]["code"]

        if sec:
            self._result_section_title(scroll, "隐藏分支下的「常规判决」参考")
            note = (
                f"页面主结果为「{code_final}」。若忽略酒精异常规则，算法本应最接近「{sec['code']}（{sec['cn']}）」"
                f"：相似度 {sec['similarity']}%，命中 {sec['exact']}/15 维，距离 {sec['distance']}。\n\n"
                f"以下为该人格的完整解读，可与当前主结果对照阅读："
            )
            self._result_readonly_text(scroll, note, height=130)
            self._result_readonly_text(scroll, sec.get("desc", ""), height=320)

        elif result.get("special") and code_final == "HHHH":
            self._result_section_title(scroll, "低于 60% 阈值时，标准库第一名是谁")
            note = (
                f"标准人格库最高匹配仅 {bn['similarity']}%（<60%），系统于是兜底为 HHHH。\n\n"
                f"若不兜底，第一名本为「{bn['code']}（{bn['cn']}）」，"
                f"相似度 {bn['similarity']}%，命中 {bn['exact']}/15 维。\n\n"
                f"其人设解读原文如下，供侧面参考：\n\n{bn.get('desc', '')}"
            )
            self._result_readonly_text(scroll, note, height=400)

        else:
            self._result_section_title(scroll, "与最终模板的数值关系")
            pat = bn.get("pattern", "")
            note = (
                f"判定人格即标准库首位「{bn['code']}」，其模板串为：{pat}。\n"
                f"你的指纹与模板总距离 {bn['distance']}，相似度 {bn['similarity']}%。"
            )
            self._result_readonly_text(scroll, note, height=100)

    def _build_tab_match_rank(self, tab: Any, result: Dict[str, Any]) -> None:
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        ctk.CTkLabel(
            scroll,
            text=(
                "25 种标准人格完整排序（全部与程序计算一致）。"
                "排行越靠前，与你当前 L/M/H 画像越接近。"
            ),
            font=ctk.CTkFont(size=13),
            text_color=COLOR_MUTED,
            anchor="w",
            wraplength=640,
            justify="left",
        ).pack(anchor="w", pady=(0, 12), padx=4)

        ranked: List[Dict[str, Any]] = result["ranked"]
        for i, row in enumerate(ranked, start=1):
            is_top = i == 1
            fr = ctk.CTkFrame(
                scroll,
                fg_color="#edf6ef" if is_top else "#fbfdfb",
                corner_radius=14,
                border_width=1,
                border_color=COLOR_ACCENT_SOFT if is_top else COLOR_LINE,
            )
            fr.pack(fill="x", pady=5, padx=2)
            head = ctk.CTkFrame(fr, fg_color="transparent")
            head.pack(fill="x", padx=12, pady=(10, 4))
            ctk.CTkLabel(
                head,
                text=f"#{i}  {row['code']}（{row['cn']}）",
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color=COLOR_ACCENT if is_top else "#1e2a22",
            ).pack(side="left")
            ctk.CTkLabel(
                head,
                text=f"{row['similarity']}%",
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color=COLOR_ACCENT,
            ).pack(side="right")
            meta = (
                f"命中 {row['exact']}/15 维　·　总距离 {row['distance']}　·　模板 {row['pattern']}"
            )
            ctk.CTkLabel(
                fr,
                text=meta,
                font=ctk.CTkFont(size=12),
                text_color=COLOR_MUTED,
                anchor="w",
            ).pack(anchor="w", padx=12, pady=(0, 4))
            ctk.CTkLabel(
                fr,
                text=row.get("intro", ""),
                font=ctk.CTkFont(size=12),
                text_color="#5a6b62",
                anchor="w",
                wraplength=620,
                justify="left",
            ).pack(anchor="w", padx=12, pady=(0, 10))

    def _show_result(self, result: Dict[str, Any]) -> None:
        self._clear_main()
        self._last_result = result

        t = result["final_type"]
        code = t["code"]

        header = ctk.CTkFrame(self._main, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            header,
            text=result["mode_kicker"],
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLOR_ACCENT,
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text=f'{code}（{t["cn"]}）',
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color="#1e2a22",
        ).pack(anchor="w", pady=(4, 4))

        badge_fr = ctk.CTkFrame(
            header, fg_color="#edf6ef", corner_radius=20, border_width=1, border_color=COLOR_LINE
        )
        badge_fr.pack(anchor="w", pady=(4, 0))
        ctk.CTkLabel(
            badge_fr,
            text=f"  {result['badge']}  ",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLOR_ACCENT,
        ).pack(padx=6, pady=8)

        ctk.CTkLabel(
            header,
            text=result["sub"],
            font=ctk.CTkFont(size=14),
            text_color=COLOR_MUTED,
            wraplength=920,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

        body = ctk.CTkFrame(self._main, fg_color="transparent")
        body.pack(fill="both", expand=True)

        left = ctk.CTkFrame(
            body,
            fg_color=COLOR_CARD,
            corner_radius=20,
            border_width=1,
            border_color=COLOR_LINE,
            width=340,
        )
        left.pack(side="left", fill="y", padx=(0, 14))
        left.pack_propagate(False)

        img_path = resolve_type_image_path(code)
        if img_path:
            try:
                pil = Image.open(img_path).convert("RGBA")
                max_w, max_h = 300, 420
                try:
                    resample = Image.Resampling.LANCZOS
                except AttributeError:
                    resample = Image.LANCZOS  # Pillow < 10
                pil.thumbnail((max_w, max_h), resample)
                ctk_img = ctk.CTkImage(light_image=pil, dark_image=pil, size=pil.size)
                img_lbl = ctk.CTkLabel(left, image=ctk_img, text="")
                img_lbl.pack(pady=(20, 8), padx=16)
                img_lbl._image_ref = ctk_img  # 防止被 GC
            except OSError:
                ctk.CTkLabel(
                    left,
                    text="图片加载失败",
                    text_color=COLOR_MUTED,
                ).pack(pady=40)
        else:
            ctk.CTkLabel(
                left,
                text="未找到配图\n请将图片置于 image 目录",
                font=ctk.CTkFont(size=14),
                text_color=COLOR_MUTED,
                justify="center",
            ).pack(pady=60, padx=16)

        ctk.CTkLabel(
            left,
            text=t["intro"],
            font=ctk.CTkFont(size=14),
            text_color=COLOR_MUTED,
            wraplength=300,
            justify="center",
        ).pack(side="bottom", pady=(8, 20), padx=12)

        right = ctk.CTkFrame(
            body,
            fg_color=COLOR_CARD,
            corner_radius=20,
            border_width=1,
            border_color=COLOR_LINE,
        )
        right.pack(side="left", fill="both", expand=True)

        tabs = ctk.CTkTabview(
            right,
            fg_color=COLOR_CARD,
            segmented_button_selected_color=COLOR_ACCENT,
            segmented_button_selected_hover_color="#3d5642",
        )
        tabs.pack(fill="both", expand=True, padx=12, pady=12)

        tab_desc = tabs.add("解读")
        desc_box = ctk.CTkTextbox(
            tab_desc,
            font=ctk.CTkFont(size=15),
            text_color="#304034",
            fg_color="#fbfdfb",
            border_width=1,
            border_color=COLOR_LINE,
            corner_radius=12,
        )
        desc_box.pack(fill="both", expand=True, padx=8, pady=8)
        desc_box.insert("1.0", t["desc"])
        desc_box.configure(state="disabled")

        tab_analysis = tabs.add("综合分析")
        self._build_tab_comprehensive_analysis(tab_analysis, result)

        tab_rank = tabs.add("匹配排行")
        self._build_tab_match_rank(tab_rank, result)

        tab_dim = tabs.add("十五维度")
        dim_scroll = ctk.CTkScrollableFrame(tab_dim, fg_color="transparent")
        dim_scroll.pack(fill="both", expand=True, padx=4, pady=4)

        first_grp = True
        for grp_title, dims in DIMENSION_MODEL_GROUPS:
            ctk.CTkLabel(
                dim_scroll,
                text=grp_title,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=COLOR_ACCENT_SOFT,
                anchor="w",
            ).pack(anchor="w", pady=(8 if first_grp else 18, 8), padx=4)
            first_grp = False
            for dim in dims:
                lv = result["levels"][dim]
                sc = result["raw_scores"][dim]
                name = DIMENSION_META[dim]["name"]
                model = DIMENSION_META[dim]["model"]
                expl = DIM_EXPLANATIONS[dim][lv]
                row = ctk.CTkFrame(
                    dim_scroll,
                    fg_color="#ffffff",
                    corner_radius=14,
                    border_width=1,
                    border_color=COLOR_LINE,
                )
                row.pack(fill="x", pady=6)
                head = ctk.CTkFrame(row, fg_color="transparent")
                head.pack(fill="x", padx=14, pady=(12, 4))
                ctk.CTkLabel(
                    head,
                    text=f"{name}",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color="#1e2a22",
                ).pack(side="left")
                ctk.CTkLabel(
                    head,
                    text=f"{lv} / {sc}分",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=COLOR_ACCENT,
                ).pack(side="right")
                ctk.CTkLabel(
                    row,
                    text=f"所属：{model}",
                    font=ctk.CTkFont(size=11),
                    text_color=COLOR_MUTED,
                    anchor="w",
                ).pack(anchor="w", padx=14, pady=(0, 4))
                ctk.CTkLabel(
                    row,
                    text=expl,
                    font=ctk.CTkFont(size=13),
                    text_color=COLOR_MUTED,
                    wraplength=620,
                    justify="left",
                ).pack(anchor="w", padx=14, pady=(0, 12))

        foot = ctk.CTkFrame(self._main, fg_color="transparent")
        foot.pack(fill="x", pady=(14, 0))

        ctk.CTkLabel(
            foot,
            text=result["fun_note"],
            font=ctk.CTkFont(size=13),
            text_color=COLOR_MUTED,
            wraplength=960,
            justify="left",
        ).pack(anchor="w")

        btn_row = ctk.CTkFrame(foot, fg_color="transparent")
        btn_row.pack(fill="x", pady=(12, 0))
        ctk.CTkButton(
            btn_row,
            text="再测一次",
            width=130,
            height=40,
            fg_color=COLOR_ACCENT,
            hover_color="#3d5642",
            command=self._start_quiz,
        ).pack(side="right")
        ctk.CTkButton(
            btn_row,
            text="保存身份卡片",
            width=130,
            height=40,
            fg_color=COLOR_ACCENT_SOFT,
            hover_color="#5a7a5f",
            text_color="#ffffff",
            command=self._save_identity_card,
        ).pack(side="right", padx=(0, 10))
        ctk.CTkButton(
            btn_row,
            text="返回首页",
            width=130,
            height=40,
            fg_color=COLOR_CARD,
            text_color=COLOR_ACCENT,
            border_width=1,
            border_color=COLOR_LINE,
            hover_color="#edf6ef",
            command=self._show_intro,
        ).pack(side="right", padx=(0, 10))

    def _save_identity_card(self) -> None:
        r = getattr(self, "_last_result", None)
        if not r:
            return
        code = r["final_type"]["code"]
        poster = resolve_type_image_path(code)
        dlg = ExportCardChoiceDialog(self)
        self.wait_window(dlg)
        if dlg.choice == "direct":
            safe = "".join(c if c not in '<>:"/\\|?*' else "_" for c in code)
            path = filedialog.asksaveasfilename(
                parent=self,
                defaultextension=".png",
                filetypes=[("PNG 图片", "*.png")],
                initialfile=f"SBTI_{safe}.png",
                title="保存身份卡片",
            )
            if not path:
                return
            try:
                img = render_identity_card_base(r, poster)
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                img.save(path, format="PNG", optimize=True)
            except Exception as e:
                messagebox.showerror("保存失败", str(e), parent=self)
                return
            messagebox.showinfo("已保存", path, parent=self)
        elif dlg.choice == "edit":
            CardStickerEditor(self, r, poster)


def main() -> None:
    app = SBTIApp()
    app.mainloop()


if __name__ == "__main__":
    main()
