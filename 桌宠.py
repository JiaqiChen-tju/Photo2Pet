# -*- coding: utf-8 -*-
"""Photo2Pet —— 三视图透明桌宠（离线单机版）。

纯本地运行：不需要联网、不需要 API Key、不需要安装插件。
左键单击：蹦跳 + 随机说一句；双击：喂食；右键：完整菜单。
素材可用 --assets 指向外部素材包，换角色不用改代码。
"""
import ctypes
import json
import math
import os
import random
import subprocess
import sys
import traceback

import psutil

try:
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import pynvml
    pynvml.nvmlInit()
    GPU_AVAILABLE = True
except Exception:
    GPU_AVAILABLE = False

from PySide6.QtCore import Qt, QTimer, QPoint, QPointF, QRectF
from PySide6.QtGui import (QPainter, QPixmap, QFont, QColor, QIcon, QFontMetrics,
                           QPolygonF, QImageReader, QPen)
from PySide6.QtWidgets import (QApplication, QWidget, QMenu, QSystemTrayIcon,
                               QMessageBox, QHBoxLayout, QToolButton)


def _configure_console():
    """Avoid UnicodeEncodeError on non-UTF-8 consoles (e.g. English Windows)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


_configure_console()

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
    PYTHONW = sys.executable
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR
    PYTHONW = os.path.join(APP_DIR, ".venv", "Scripts", "pythonw.exe")

CONFIG_PATH = os.path.join(APP_DIR, "config.json")

BUBBLE_H = 90
MARGIN = 4
SPEED = 380.0
TICK = 20

DEFAULT_NAME = "小桌宠"
DEFAULT_LINES = []
DEFAULT_SIZE_LEVELS = {"小": 0.55, "中": 0.7, "大": 0.9}


def arg_value(flag):
    """从命令行取 --flag value / --flag=value 的值。"""
    argv = sys.argv
    for i, item in enumerate(argv):
        if item == flag and i + 1 < len(argv):
            return argv[i + 1]
        if item.startswith(flag + "="):
            return item.split("=", 1)[1]
    return None


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# 身份配置：优先读外部素材包，其次读本地 config.json，都没有就用默认值
LOCAL_CFG = read_json(CONFIG_PATH)
ASSETS_ARG = arg_value("--assets")
ASSETS_CFG = read_json(os.path.join(ASSETS_ARG, "config.json")) if ASSETS_ARG else {}
IDENT_CFG = ASSETS_CFG if ASSETS_CFG.get("name") else LOCAL_CFG

APP_NAME = str(IDENT_CFG.get("name") or DEFAULT_NAME)
PET_LINES = [str(x) for x in (IDENT_CFG.get("lines") or DEFAULT_LINES)]
SIZE_LEVELS = dict(IDENT_CFG.get("size_levels") or DEFAULT_SIZE_LEVELS)
FRAME_COUNT = int(IDENT_CFG.get("frames") or 16)


def _resolve_assets_root():
    cand = ASSETS_ARG or LOCAL_CFG.get("asset_dir")
    if not cand:
        return None
    if os.path.isabs(cand):
        return cand if os.path.isdir(cand) else None
    # 相对路径先按 exe 同目录解析（素材包和 exe 放一起的常见用法），
    # 找不到再按当前工作目录解析（命令行传相对路径的用法）
    for base in (APP_DIR, os.getcwd()):
        path = os.path.join(base, cand)
        if os.path.isdir(path):
            return path
    return None


ASSETS_ROOT = _resolve_assets_root()


def asset_dir(rel, bundle_rel):
    """指定了外部素材包就只用包内的（不做混用），否则用打包内置素材。"""
    if ASSETS_ROOT:
        return os.path.join(ASSETS_ROOT, rel)
    return os.path.join(BUNDLE_DIR, bundle_rel)


SPRITE_DIR = asset_dir("sprites", "sprites")
EXPR_DIR = asset_dir(os.path.join("assets", "expressions"), os.path.join("assets", "expressions"))
DANCE_DIR = asset_dir(os.path.join("assets", "dance"), os.path.join("assets", "dance"))

FOODS = ["🍰", "🍭", "🍡", "🍓", "🍪"]


def pick_line():
    return random.choice(PET_LINES) if PET_LINES else ""


def load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=4)
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


class FoodPanel(QWidget):
    """双击弹出的喂食面板"""

    def __init__(self, on_pick):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(310, 64)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        for f in FOODS:
            b = QToolButton()
            b.setText(f)
            b.setFont(QFont("Segoe UI Emoji", 20))
            b.setFixedSize(44, 44)
            b.setStyleSheet(
                "QToolButton{background:rgba(255,255,255,235);border:2px solid #ffb3c8;"
                "border-radius:22px;} QToolButton:hover{background:#ffe3ec;border-color:#ff7fa8;}")
            b.clicked.connect(lambda _, x=f: on_pick(x))
            lay.addWidget(b)
        close = QToolButton()
        close.setText("✕")
        close.setFont(QFont("Microsoft YaHei UI", 12))
        close.setFixedSize(26, 26)
        close.setStyleSheet("QToolButton{background:rgba(255,255,255,200);border:none;border-radius:13px;color:#666;}"
                            "QToolButton:hover{background:#ff7fa8;color:#fff;}")
        close.clicked.connect(self.hide)
        lay.addWidget(close)
        self.setStyleSheet("FoodPanel{background:rgba(40,40,60,190);border-radius:14px;}")

    def popup_at(self, x, y):
        self.move(int(x - self.width() / 2), int(y - self.height() - 10))
        self.show()
        self.raise_()


class PetWindow(QWidget):
    def __init__(self):
        self.cfg = load_json(CONFIG_PATH, {
            "mode": "wander",
            "size": 0.7,
            "topmost": True,
            "passthrough": False,
            "autostart": False,
            "x": None,
            "y": None,
        })

        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.cfg.get("topmost", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(APP_NAME)

        # 精灵加载
        self.sprites = {}
        for label, mult in SIZE_LEVELS.items():
            h = int(340 * mult)
            for name in ["front", "side", "back"]:
                sized = os.path.join(SPRITE_DIR, f"{name}_{h}.png")
                if os.path.exists(sized):
                    pix = QPixmap(sized)
                else:
                    pix = QPixmap(os.path.join(SPRITE_DIR, f"{name}.png")).scaledToHeight(
                        h, Qt.TransformationMode.SmoothTransformation)
                self.sprites[(name, h)] = pix
        self.icon = QIcon(os.path.join(SPRITE_DIR, "icon.png"))

        # 拆件舞蹈帧：左右手臂/鞋子分区驱动后烘焙的透明帧
        self.dance_frames = {}
        for h in sorted({int(340 * mult) for mult in SIZE_LEVELS.values()}):
            frames = []
            for index in range(FRAME_COUNT):
                frame_path = os.path.join(DANCE_DIR, f"front_{index:02d}.png")
                if not os.path.exists(frame_path):
                    continue
                pix = QPixmap(frame_path)
                if pix.isNull():
                    continue
                frames.append(pix.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation))
            if frames:
                self.dance_frames[h] = frames

        self.cur_h = int(340 * self.cfg.get("size", 0.7))
        self.win_mx = int(self.cur_h * 0.062) + 6
        self.win_w = max(p.width() for k, p in self.sprites.items() if k[1] == self.cur_h) + self.win_mx * 2
        self.setFixedSize(self.win_w, self.cur_h + BUBBLE_H + MARGIN * 2 + 10)

        # 状态
        self.mode = self.cfg.get("mode", "wander")
        if self.mode not in ("wander", "follow", "still"):
            self.mode = "wander"
        self.dir = "down"
        self.facing = 1
        self.target = None
        self.rest_until = 0
        self.cur_speed = 0.0
        self.prev_key = None
        self.cross_t = 0.0
        self.action = None
        self.action_t = 0.0
        self.bubble_text = ""
        self.bubble_until = 0
        self.banner_text = ""
        self.banner_start = 0.0
        self.banner_until = 0.0
        self.last_system_check = 0
        self.t = 0
        self.jump_t = 0
        self.dance_t = 0.0
        self.dance_style = 0
        self.dragging = False
        self.drag_offset = None
        self.drag_start_pos = None
        self.last_line = ""
        self.last_press_pos = None

        # 自定义表情
        self.is_custom_expression = False
        self.custom_expression_path = ""
        self.custom_expression_name = ""
        self._expr_source = None
        self._expr_scaled = None

        self.food_panel = FoodPanel(self.on_food)
        # 单击延迟判定（等双击）：单击=回嘴，双击=喂食
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._on_single_click)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK)

        self.bubble_font = QFont("Microsoft YaHei UI", 14, QFont.Weight.Bold)

        # 托盘
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip(APP_NAME)
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is None or y is None:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.right() - self.width() - 80
            y = screen.bottom() - self.height() - 60
        self.move(int(x), int(y))
        self.show()
        self.snap_into_screen()
        if self.cfg.get("passthrough", False):
            self._apply_passthrough(True)

    # ---------- 自定义表情 ----------
    def _expression_files(self):
        if not os.path.isdir(EXPR_DIR):
            return []
        items = []
        for filename in os.listdir(EXPR_DIR):
            if filename.lower().endswith((".png", ".webp", ".jpg", ".jpeg")):
                path = os.path.join(EXPR_DIR, filename)
                if os.path.isfile(path):
                    items.append((os.path.splitext(filename)[0], path))
        items.sort(key=lambda item: item[0])
        return items

    def _update_expression_pixmap(self):
        if not self.is_custom_expression or self._expr_source is None:
            return
        src = self._expr_source
        screen = self.screen() or QApplication.primaryScreen()
        avail_w = screen.availableGeometry().width() if screen is not None else 1920
        max_expr_w = max(1, avail_w - 40)

        target_h = self.cur_h
        natural_w = max(1, round(src.width() * target_h / src.height()))
        if natural_w > max_expr_w:
            target_h = max(1, round(src.height() * max_expr_w / src.width()))
            natural_w = max_expr_w

        scaled = src.scaled(
            natural_w, target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._expr_scaled = scaled

        new_w = max(self.win_w, scaled.width() + 2 * MARGIN)
        new_w = min(new_w, max(self.win_w, avail_w - 20))
        if new_w != self.width():
            center_x = self.x() + self.width() // 2
            height = self.height()
            self.setFixedSize(new_w, height)
            self.move(center_x - new_w // 2, self.y())
            self.snap_into_screen()

    def _restore_window_width(self):
        if self.width() != self.win_w:
            center_x = self.x() + self.width() // 2
            height = self.height()
            self.setFixedSize(self.win_w, height)
            self.move(center_x - self.win_w // 2, self.y())
            self.snap_into_screen()

    def set_custom_expression(self, path):
        pix = QPixmap(path)
        if pix.isNull():
            self.say("表情图片加载失败")
            return False
        self._expr_source = pix
        self.custom_expression_path = path
        self.custom_expression_name = os.path.splitext(os.path.basename(path))[0]
        self.is_custom_expression = True
        self.prev_key = None
        self.cross_t = 0.0
        self._expr_scaled = None
        self._update_expression_pixmap()
        self.update()
        self.show_expression_banner(self.custom_expression_name)
        return True

    def clear_custom_expression(self):
        was_custom = self.is_custom_expression
        self.is_custom_expression = False
        self.custom_expression_path = ""
        self.custom_expression_name = ""
        self._expr_source = None
        self._expr_scaled = None
        self.prev_key = None
        self.cross_t = 0.0
        self._restore_window_width()
        self.update()
        if was_custom:
            self.show_expression_banner("默认表情")

    # ---------- 绘制 ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 透明窗口每次重绘前清空，避免连续帧叠影
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        now = self.t * TICK / 1000.0

        if self.bubble_text and now < self.bubble_until:
            bfont = QFont(self.bubble_font)
            bg, fg = QColor(255, 255, 255, 235), QColor(60, 60, 80)
            fm = QFontMetrics(bfont)
            max_w = min(240, self.width() - 16)
            words = self.bubble_text
            lines = []
            cur = ""
            for ch in words:
                if fm.horizontalAdvance(cur + ch) > max_w - 20:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            lines.append(cur)
            bw = max(fm.horizontalAdvance(l) for l in lines) + 20
            bh = len(lines) * fm.height() + 14
            bx = (self.width() - bw) / 2
            by = 6.0
            p.setPen(QPen(QColor(255, 170, 200, 230), 2))
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 12, 12)
            tail = QPointF(self.width() / 2, by + bh)
            p.setPen(QPen(QColor(255, 170, 200, 230), 2))
            p.setBrush(bg)
            p.drawPolygon(QPolygonF([tail, QPointF(tail.x() - 7, tail.y() + 9),
                                     QPointF(tail.x() + 7, tail.y() + 9)]))
            p.setPen(fg)
            p.setFont(bfont)
            for i, l in enumerate(lines):
                p.drawText(QRectF(bx, by + 8 + i * fm.height(), bw, fm.height()),
                           Qt.AlignmentFlag.AlignCenter, l)

        self._draw_expression_banner(p, now)

        cx = self.width() / 2
        walking = self.target is not None and not self.dragging
        if walking:
            sway = math.sin(now * 9.0) * 3.5
            bob = -abs(math.sin(now * 4.5)) * 7.0
        else:
            sway = math.sin(now * 2.5) * 1.5
            bob = 0.0
        breath = 1.0 + 0.02 * math.sin(now * 2.5)
        scale = breath
        jump = -abs(math.sin(self.jump_t * 3.14159)) * 14 * self.jump_t if self.jump_t > 0 else 0
        act_rot = act_sx = act_sy = 0.0
        if self.action == "sway":
            act_rot = math.sin(self.action_t * 3.14159 * 2) * 10 * self.action_t
        elif self.action == "stretch":
            act_sy = 0.06 * math.sin(self.action_t * 3.14159)
            act_sx = -0.03 * math.sin(self.action_t * 3.14159)

        # 待机舞蹈：用身体摇摆、弹跳、扭转和踏步节奏模拟手脚律动
        dance_rot = dance_dx = dance_sy = dance_sx = 0.0
        if self.dance_t > 0 and not walking and not self.dragging:
            elapsed = 1.0 - self.dance_t
            beat = elapsed * math.pi * 2
            if self.dance_style == 0:
                # 左右摇摆 + 双脚交替轻跳
                dance_rot = math.sin(beat * 3) * 7
                dance_dx = math.sin(beat * 1.5) * 6
                bob -= abs(math.sin(beat * 6)) * 7
                dance_sy = 0.03 * math.sin(beat * 6)
            elif self.dance_style == 1:
                # 扭腰 + 快速小碎步
                dance_rot = math.sin(beat * 4) * 11
                dance_dx = math.sin(beat * 2) * 4
                bob -= abs(math.sin(beat * 8)) * 5
                dance_sy = 0.04 * math.sin(beat * 8)
            else:
                # 大幅左右踏步 + 蹦跳
                dance_rot = math.sin(beat * 2) * 9
                dance_dx = math.sin(beat * 4) * 8
                bob -= abs(math.sin(beat * 4)) * 10
                dance_sy = 0.05 * math.sin(beat * 4)
            dance_sx = -0.55 * dance_sy

        # 自定义表情：锁定显示，不被走路状态机覆盖
        if self.is_custom_expression and self._expr_scaled is not None:
            pix = self._expr_scaled
            ph = pix.height() * scale
            pw = pix.width() * scale
            bottom = BUBBLE_H + MARGIN + self.cur_h
            dx = cx - pw / 2
            dy = bottom - ph
            p.save()
            p.translate(cx, bottom)
            p.rotate(sway)
            p.translate(-cx, -bottom)
            p.drawPixmap(QRectF(dx, dy, pw, ph), pix,
                         QRectF(0, 0, pix.width(), pix.height()))
            p.restore()
            return

        # 拆件帧动画：手脚独立动作已经烘焙在帧里
        if self.dance_t > 0 and not walking and not self.dragging:
            frames = self.dance_frames.get(self.cur_h)
            if frames:
                index = int((1.0 - self.dance_t) * 48) % len(frames)
                pix = frames[index]
                ph = pix.height() * scale
                pw = pix.width() * scale
                bottom = BUBBLE_H + MARGIN + self.cur_h
                dx = cx - pw / 2
                dy = bottom - ph
                p.drawPixmap(QRectF(dx, dy, pw, ph), pix,
                             QRectF(0, 0, pix.width(), pix.height()))
                return

        def draw_one(key, opacity):
            if key is None:
                return
            name, h, facing = key
            pix = self.sprites[(name, h)]
            ph = pix.height() * scale * (1 + act_sy + dance_sy)
            pw = pix.width() * scale * (1 + act_sx + dance_sx)
            dx = cx - pw / 2 + dance_dx
            bottom = BUBBLE_H + MARGIN + self.cur_h
            dy = bottom - ph + jump + bob
            p.save()
            p.setOpacity(opacity)
            p.translate(cx, bottom)
            p.rotate(sway + act_rot + dance_rot)
            p.translate(-cx, -bottom)
            if facing < 0:
                p.translate(cx, 0)
                p.scale(-1, 1)
                p.translate(-cx, 0)
            p.drawPixmap(QRectF(dx, dy, pw, ph), pix, QRectF(0, 0, pix.width(), pix.height()))
            p.restore()

        cur_key = self._sprite_key()
        if self.cross_t > 0:
            draw_one(self.prev_key, self.cross_t)
            draw_one(cur_key, 1.0 - self.cross_t)
        else:
            draw_one(cur_key, 1.0)

    def _sprite_key(self):
        name = {"left": "side", "right": "side", "up": "back", "down": "front"}[self.dir]
        return (name, self.cur_h, self.facing if self.dir in ("left", "right") else 1)

    def _set_dir(self, d, facing=None):
        if d != self.dir:
            self.prev_key = self._sprite_key()
            self.cross_t = 1.0
            self.dir = d
        if facing is not None and facing != self.facing:
            self.facing = facing

    # ---------- 逻辑 ----------
    def tick(self):
        self.t += 1
        self.check_system_status()

        if self.jump_t > 0:
            self.jump_t = max(0.0, self.jump_t - 0.06)
        if self.cross_t > 0:
            self.cross_t = max(0.0, self.cross_t - 0.15)
        if self.action_t > 0:
            self.action_t = max(0.0, self.action_t - 0.03)
            if self.action_t == 0:
                self.action = None
        if self.dance_t > 0:
            self.dance_t = max(0.0, self.dance_t - 0.006)

        if self.dragging:
            self.update()
            return
        now_ms = self.t * TICK

        if self.mode == "follow":
            cursor = self.cursor().pos()
            screen = QApplication.screenAt(cursor) or self.screen() or QApplication.primaryScreen()
            geo = screen.availableGeometry()
            near = (self.x() - 100 <= cursor.x() <= self.x() + self.width() + 100 and
                    self.y() - 100 <= cursor.y() <= self.y() + self.height() + 100)
            if near:
                self.target = None
            else:
                tx = max(geo.left(), min(geo.right() - self.width(), cursor.x() - self.width() / 2))
                ty = max(geo.top(), min(geo.bottom() - self.height(), cursor.y() - 90))
                self.target = (tx, ty)
        elif self.mode == "wander":
            if self.target is None:
                if now_ms < self.rest_until:
                    self._maybe_idle_action()
                    self.update()
                    return
                geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
                self.target = (random.randint(geo.left() + 40, geo.right() - self.width() - 40),
                               random.randint(geo.top() + 40, geo.bottom() - self.height() - 40))
        else:
            self._maybe_idle_action()
            self.update()
            return

        if self.target is not None and self.dance_t > 0:
            self.dance_t = 0.0

        if self.target is not None:
            cx, cy = self.x() + self.width() / 2, self.y() + self.height() / 2
            dx, dy = self.target[0] - cx, self.target[1] - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < 12:
                self.target = None
                self.rest_until = self.t * TICK + random.randint(8000, 18000)
                self._set_dir("down")
            else:
                step = self.cur_speed * TICK / 1000.0
                nx, ny = cx + dx / dist * step, cy + dy / dist * step
                self.move(int(nx - self.width() / 2), int(ny - self.height() / 2))
                if abs(dx) > abs(dy) * 1.15:
                    self._set_dir("left" if dx < 0 else "right", 1 if dx < 0 else -1)
                else:
                    self._set_dir("up" if dy < 0 else "down")
            if random.random() < 0.002 and self.jump_t == 0:
                self.jump_t = 0.5
        target_speed = SPEED if self.target is not None else 0.0
        self.cur_speed += (target_speed - self.cur_speed) * 0.3
        self.update()

    def start_dance(self, manual=False):
        """开始一段约 3 秒的待机舞蹈。"""
        if manual:
            self.target = None
            self.cur_speed = 0.0
            self.rest_until = self.t * TICK + 4000
        self.dance_t = 1.0
        self.dance_style = random.choice((0, 1, 2))
        self.dir = "down"
        self.facing = 1
        self.prev_key = None
        self.cross_t = 0.0
        self.jump_t = 0.0
        self.action = None
        self.action_t = 0.0
        # 台词只在左键单击时出现，跳舞本身不出声

    def _maybe_idle_action(self):
        if self.dance_t > 0:
            return
        if random.random() < 0.012:
            pick = random.random()
            if pick < 0.2:
                self.jump_t = 1.0
            elif pick < 0.38:
                self.action, self.action_t = "sway", 1.0
            elif pick < 0.54:
                self.action, self.action_t = "stretch", 1.0
            else:
                self.start_dance()

    def show_expression_banner(self, text):
        """切换表情时在头顶显示醒目的表情名称气泡。"""
        self.banner_text = text
        self.banner_start = self.t * TICK / 1000.0
        self.banner_until = self.banner_start + 2.8
        self.bubble_text = ""
        self.bubble_until = 0
        self.update()

    def _draw_expression_banner(self, p, now):
        if not self.banner_text or now >= self.banner_until:
            return
        font = QFont("Microsoft YaHei UI", 18, QFont.Weight.Bold)
        fm = QFontMetrics(font)
        wrap_w = max(60, self.width() - 32)
        text = self.banner_text
        if fm.horizontalAdvance(text) <= wrap_w:
            lines = [text]
        else:
            best = None
            for split in range(1, len(text)):
                left, right = text[:split], text[split:]
                if (fm.horizontalAdvance(left) <= wrap_w
                        and fm.horizontalAdvance(right) <= wrap_w):
                    score = abs(len(left) - len(right))
                    candidate = (score, -len(left), left, right)
                    if best is None or candidate[:2] < best[:2]:
                        best = candidate
            if best is not None:
                lines = [best[2], best[3]]
            else:
                lines = []
                current = ""
                for ch in text:
                    if fm.horizontalAdvance(current + ch) > wrap_w:
                        lines.append(current)
                        current = ch
                    else:
                        current += ch
                lines.append(current)
        bw = max(fm.horizontalAdvance(line) for line in lines) + 26
        bh = len(lines) * fm.height() + 20
        bx = (self.width() - bw) / 2
        by = 4.0
        cx = self.width() / 2

        age = max(0.0, now - self.banner_start)
        pop = 0.72 + 0.28 * min(1.0, age / 0.18)

        p.save()
        p.translate(cx, by + bh / 2)
        p.scale(pop, pop)
        p.translate(-cx, -(by + bh / 2))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawRoundedRect(QRectF(bx + 2, by + 3, bw, bh), 18, 18)

        p.setPen(QPen(QColor(255, 170, 200, 240), 3))
        p.setBrush(QColor(255, 205, 82, 248))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), 18, 18)
        p.setPen(QPen(QColor(255, 255, 255, 245), 3))
        p.setBrush(QColor(255, 205, 82, 248))
        p.drawPolygon(QPolygonF([
            QPointF(cx - 11, by + bh - 2),
            QPointF(cx + 11, by + bh - 2),
            QPointF(cx, by + bh + 11),
        ]))

        p.setFont(font)
        for index, line in enumerate(lines):
            rect = QRectF(bx, by + 10 + index * fm.height(), bw, fm.height())
            p.setPen(QColor(120, 60, 0, 110))
            p.drawText(rect.translated(1, 2), Qt.AlignmentFlag.AlignCenter, line)
            p.setPen(QColor(78, 34, 0))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, line)
        p.restore()

    def say(self, text):
        if text == self.last_line:
            return
        self.banner_text = ""
        self.banner_until = 0.0
        self.last_line = text
        self.bubble_text = text
        self.bubble_until = self.t * TICK / 1000.0 + 2.8
        self.update()

    def check_system_status(self):
        now = self.t * TICK
        if now - self.last_system_check < 10000:
            return
        self.last_system_check = now

        cpu = psutil.cpu_percent()
        if cpu >= 90:
            self.say("CPU跑满了，再这样下去我就卡死了")
            return

        ram = psutil.virtual_memory().percent
        if ram >= 95:
            self.say("内存爆了，快关掉几个没用的东西吧，注意，别把我关了")
            return

        if GPU_AVAILABLE:
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                if temp > 80:
                    self.say("我感觉电脑快热熟了")
            except Exception as e:
                print("GPU read failed:", e)

    # ---------- 鼠标事件 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.last_press_pos = e.globalPosition().toPoint()
            self.dragging = False
            self.drag_start_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self.drag_start_pos is not None:
            delta = e.globalPosition().toPoint() - self.drag_start_pos
            if not self.dragging and delta.manhattanLength() > 6:
                self.dragging = True
                self.drag_offset = e.globalPosition().toPoint() - QPoint(self.x(), self.y())
            if self.dragging and self.drag_offset is not None:
                pos = e.globalPosition().toPoint() - self.drag_offset
                self.move(pos)
                if abs(delta.x()) > 10:
                    self._set_dir("left" if delta.x() < 0 else "right", 1 if delta.x() < 0 else -1)
                self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self.dragging:
                self.dragging = False
                self.drag_offset = None
                self.drag_start_pos = None
                self._set_dir("down", 1)
                self.target = None
                self.rest_until = self.t * TICK + random.randint(6000, 14000)
            else:
                self._click_timer.start(280)  # 等双击判定
            self.last_press_pos = None
            self.drag_start_pos = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.food_panel.popup_at(self.x() + self.width() / 2, self.y() + BUBBLE_H)

    def _on_single_click(self):
        """单击：蹦跳 + 说一句（台词只在这里出现）"""
        if random.random() < 0.7:
            self.jump_t = 1.0
        self.say(pick_line())

    def on_food(self, food):
        self.food_panel.hide()
        self.jump_t = 0.6

    # ---------- 菜单 ----------
    def _build_menu(self):
        m = QMenu(self)
        mode_menu = m.addMenu("模式")
        for label, key in [("自由散步", "wander"), ("跟随鼠标", "follow"), ("原地待着", "still")]:
            a = mode_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.mode == key)
            a.triggered.connect(lambda _, k=key: self.set_mode(k))
        size_menu = m.addMenu("大小")
        for label, mult in SIZE_LEVELS.items():
            a = size_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(self.cur_h - 340 * mult) < 2)
            a.triggered.connect(lambda _, v=mult: self.set_size(v))

        expr_menu = m.addMenu("切换表情")
        expr_menu.addAction("恢复默认", lambda: self.clear_custom_expression())
        expr_menu.addSeparator()
        items = self._expression_files()
        if not items:
            placeholder = expr_menu.addAction("（未找到表情图片）")
            placeholder.setEnabled(False)
        for name, path in items:
            expr_menu.addAction(name, lambda p=path: self.set_custom_expression(p))

        m.addSeparator()
        m.addAction("跳个舞", lambda: self.start_dance(manual=True))
        m.addAction("显示/隐藏", self.toggle_visible)
        m.addAction("回到屏幕内", self.snap_into_screen)
        pa = m.addAction("鼠标穿透（点不到它）")
        pa.setCheckable(True)
        pa.setChecked(self.cfg.get("passthrough", False))
        pa.triggered.connect(lambda on: self.set_passthrough(on))
        ta = m.addAction("窗口置顶")
        ta.setCheckable(True)
        ta.setChecked(self.cfg.get("topmost", True))
        ta.triggered.connect(lambda on: self.set_topmost(on))
        aa = m.addAction("开机自启")
        aa.setCheckable(True)
        aa.setChecked(self.cfg.get("autostart", False))
        aa.triggered.connect(lambda on: self.set_autostart(on))
        m.addSeparator()
        m.addAction("退出", self.quit_app)
        return m

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Context:
            self.tray.setContextMenu(self._build_menu())
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visible()

    def contextMenuEvent(self, e):
        self._build_menu().exec(e.globalPos())

    # ---------- 功能 ----------
    def set_mode(self, mode):
        self.mode = mode
        self.target = None
        self.cfg["mode"] = mode

    def set_size(self, mult):
        self.cur_h = int(340 * mult)
        self.cfg["size"] = mult
        self.cross_t = 0.0
        self.prev_key = None
        self.win_mx = int(self.cur_h * 0.062) + 6
        self.win_w = max(p.width() for k, p in self.sprites.items() if k[1] == self.cur_h) + self.win_mx * 2
        self.setFixedSize(self.win_w, self.cur_h + BUBBLE_H + MARGIN * 2 + 10)
        self.snap_into_screen()
        if self.is_custom_expression:
            self._expr_scaled = None
            self._update_expression_pixmap()
            self.update()

    def snap_into_screen(self):
        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        x = max(geo.left(), min(geo.right() - self.width(), self.x()))
        y = max(geo.top(), min(geo.bottom() - self.height(), self.y()))
        self.move(x, y)

    def _apply_passthrough(self, on):
        hwnd = int(self.winId())
        GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x80000, 0x20
        style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        style = style | WS_EX_LAYERED
        if on:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)

    def set_passthrough(self, on):
        self.cfg["passthrough"] = bool(on)
        self._apply_passthrough(bool(on))
        if on:
            self.say("我隐身了！右键托盘图标解除～")

    def set_topmost(self, on):
        self.cfg["topmost"] = bool(on)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
        self.show()

    def set_autostart(self, on):
        self.cfg["autostart"] = bool(on)
        lnk = os.path.join(os.environ.get("APPDATA", APP_DIR), "Microsoft", "Windows",
                           "Start Menu", "Programs", "Startup", f"{APP_NAME}.lnk")
        try:
            if on:
                ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{}');"
                      "$s.TargetPath='{}';$s.Arguments='\"{}\"';$s.WorkingDirectory='{}';$s.Save()"
                      .format(lnk, PYTHONW,
                              "" if getattr(sys, "frozen", False) else os.path.join(APP_DIR, "桌宠.py"),
                              APP_DIR))
                subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
                self.say("已开机自启，明天见～")
            else:
                if os.path.exists(lnk):
                    os.remove(lnk)
                self.say("已取消开机自启")
        except Exception as ex:
            QMessageBox.warning(self, "开机自启", f"设置失败：{ex}")

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def quit_app(self):
        self.cfg["x"], self.cfg["y"] = self.x(), self.y()
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        self.tray.hide()
        QApplication.quit()

    # ---------- 自检 ----------
    def run_smoke_test(self):
        report = {
            "ok": False,
            "frozen": bool(getattr(sys, "frozen", False)),
            "app_name": APP_NAME,
            "app_dir": APP_DIR,
            "bundle_dir": BUNDLE_DIR,
            "expr_dir": EXPR_DIR,
            "sprite_dir": SPRITE_DIR,
            "dance_dir": DANCE_DIR,
            "assets_root": ASSETS_ROOT,
            "pet_lines": list(PET_LINES),
            "sprite_keys": len(self.sprites),
            "sprites_missing": [],
            "expression_count": 0,
            "expression_bad": [],
            "expression_selected": None,
            "lock": False,
            "lock_cleared": False,
            "aspect_ok": False,
            "within_window": False,
            "scaled_size": None,
            "has_expression_menu": False,
            "expression_menu_items": 0,
            "expression_menu_ok": False,
            "expression_menu_selection_ok": False,
            "has_dance_menu": False,
            "dance_ok": False,
            "dance_frames": 0,
            "banner_ok": False,
        }
        try:
            expected = [(name, int(340 * mult)) for mult in SIZE_LEVELS.values()
                        for name in ("front", "side", "back")]
            report["sprites_missing"] = [
                f"{name}_{h}" for name, h in expected if (name, h) not in self.sprites
            ]

            items = self._expression_files()
            report["expression_count"] = len(items)
            report["expression_bad"] = [
                name for name, path in items if not QImageReader(path).canRead()
            ]
            if items:
                name, path = items[0]
                if self.set_custom_expression(path):
                    report["expression_selected"] = name
                    report["banner_ok"] = self.banner_text == name
                    report["lock"] = bool(self.is_custom_expression)
                    if self._expr_scaled is not None and self._expr_source is not None:
                        report["scaled_size"] = [self._expr_scaled.width(), self._expr_scaled.height()]
                        ratio_src = self._expr_source.width() / self._expr_source.height()
                        ratio_scaled = self._expr_scaled.width() / self._expr_scaled.height()
                        report["aspect_ok"] = abs(ratio_src - ratio_scaled) < 0.02
                        report["within_window"] = self._expr_scaled.width() <= self.width() - 2 * MARGIN
                    self.clear_custom_expression()
                    report["lock_cleared"] = not self.is_custom_expression

            self.start_dance()
            report["dance_ok"] = self.dance_t > 0 and self.dance_style in (0, 1, 2)
            report["dance_frames"] = len(self.dance_frames.get(self.cur_h, []))
            self.dance_t = 0.0

            menu = self._build_menu()
            titles = [a.text() for a in menu.actions()]
            report["has_dance_menu"] = "跳个舞" in titles
            report["has_expression_menu"] = "切换表情" in titles
            expr_action = next((a for a in menu.actions() if a.text() == "切换表情"), None)
            if expr_action is not None and expr_action.menu() is not None:
                non_separator = [a for a in expr_action.menu().actions() if not a.isSeparator()]
                report["expression_menu_items"] = len(non_separator)
                expected_menu = len(items) + 1 if items else 2
                report["expression_menu_ok"] = len(non_separator) == expected_menu
                if items:
                    selected_action = next(
                        (action for action in non_separator
                         if action.text() == items[0][0]),
                        None,
                    )
                    if selected_action is not None:
                        selected_action.trigger()
                        report["expression_menu_selection_ok"] = (
                            self.is_custom_expression
                            and self.custom_expression_name == selected_action.text()
                        )
                        self.clear_custom_expression()

            report["ok"] = (
                not report["sprites_missing"]
                and not report["expression_bad"]
                and (not items or (bool(report["expression_selected"])
                                   and report["lock"] and report["aspect_ok"]
                                   and report["within_window"] and report["lock_cleared"]
                                   and report["banner_ok"]))
                and report["expression_menu_ok"]
                and (not items or report["expression_menu_selection_ok"])
                and report["has_dance_menu"]
                and report["dance_ok"]
                and report["dance_frames"] == FRAME_COUNT
                and ("切换表情" in [a.text() for a in self._build_menu().actions()] if items
                     else True)
            )
        except Exception:
            report["error"] = traceback.format_exc()
        return report


def _write_smoke_report(report):
    path = os.path.join(APP_DIR, "smoke_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=True))
    return path


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    w = PetWindow()
    if "--smoke-test" in sys.argv:
        w.hide()
        report = w.run_smoke_test()
        _write_smoke_report(report)
        sys.exit(0 if report.get("ok") else 1)
    sys.exit(app.exec())


if __name__ == "__main__":
    smoke_mode = "--smoke-test" in sys.argv
    try:
        main()
    except Exception as ex:
        if smoke_mode:
            try:
                _write_smoke_report({"ok": False, "error": traceback.format_exc()})
            except Exception:
                pass
            sys.exit(1)
        try:
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, f"{APP_NAME}出错", str(ex))
        except Exception:
            pass
        raise
