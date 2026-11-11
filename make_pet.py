# -*- coding: utf-8 -*-
"""make_pet.py —— 一张照片生成桌宠素材包。

用法：
    python make_pet.py --photo 我.png --name 小明 --out pets/小明

流程：
    抠图 → 统一高度并底边对齐 → 推导侧面/背面（近似）→ 按比例锚点烘焙 16 帧舞蹈 → 写出素材包

只依赖 Pillow，不需要 numpy / scipy。抠图的 auto 模式优先用白底泛洪（纯色背景效果好），
背景复杂时会尝试 rembg（若已安装），两者都不可用时给出明确提示。
"""
import argparse
import json
import math
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageEnhance


def _configure_console():
    """Avoid UnicodeEncodeError on non-UTF-8 consoles (e.g. English Windows)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


_configure_console()

TARGET_H = 340
SIZE_LEVELS = {"小": 0.55, "中": 0.7, "大": 0.9}
FRAMES = 16
VIEWS = ("front", "side", "back")

WHITE_THRESH = 18          # 白底裁剪阈值
FLOOD_THRESH = 30          # 泛洪容差
EDGE_CLEAN_MIN = 215       # 近白判定
EDGE_CLEAN_PASSES = 3


# ---------------- 基础工具 ----------------

def load_photo(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到照片：{path}")
    return Image.open(path).convert("RGBA")


def is_white_background(im):
    """四角接近纯白且低彩度，判定为白底素材。"""
    w, h = im.size
    px = im.convert("RGB").load()
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        r, g, b = px[x, y]
        if min(r, g, b) < 228 or (max(r, g, b) - min(r, g, b)) > 18:
            return False
    return True


def cutout_white(im):
    """白底泛洪抠图：四角连通域变透明，并清理贴边近白像素。"""
    im = im.copy()
    w, h = im.size
    for sx, sy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if im.getpixel((sx, sy))[3] > 0:
            ImageDraw.floodfill(im, (sx, sy), (0, 0, 0, 0), thresh=FLOOD_THRESH)
    px = im.load()
    for _ in range(EDGE_CLEAN_PASSES):
        todo = []
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if a == 0 or min(r, g, b) < EDGE_CLEAN_MIN:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and px[nx, ny][3] == 0:
                        todo.append((x, y))
                        break
        if not todo:
            break
        for x, y in todo:
            px[x, y] = (0, 0, 0, 0)
    return im


def cutout_rembg(im):
    """背景复杂时调用 rembg（可选依赖）。"""
    try:
        from rembg import remove
    except ImportError:
        raise RuntimeError(
            "这张照片不是纯色白底，需要 rembg 才能自动抠图。\n"
            "  安装：pip install rembg\n"
            "  或者：把背景处理成纯白/透明后，用 --cutout white / --cutout alpha 重跑。"
        )
    return remove(im)


def remove_white_gaps(im, max_thickness=None):
    """清掉被前景包住的窄白缝（四肢之间的缝隙），宽大的白色主体不受影响。

    泛洪只能清掉和画布边缘连通的背景；腿缝、手臂与躯干之间的缝隙常被前景封住，
    会留下白色细条。这里按连通域处理：包围盒短边 <= 阈值（默认图像短边的 10%）视为缝隙。
    """
    im = im.copy()
    px = im.load()
    w, h = im.size
    if max_thickness is None:
        max_thickness = max(6, int(0.10 * min(w, h)))
    visited = [[False] * w for _ in range(h)]
    for y0 in range(h):
        for x0 in range(w):
            if visited[y0][x0]:
                continue
            visited[y0][x0] = True
            r, g, b, a = px[x0, y0]
            if a < 8 or min(r, g, b) < 238 or (max(r, g, b) - min(r, g, b)) > 10:
                continue
            stack, comp = [(x0, y0)], []
            x_lo = x_hi = x0
            y_lo = y_hi = y0
            while stack:
                x, y = stack.pop()
                comp.append((x, y))
                x_lo, x_hi = min(x_lo, x), max(x_hi, x)
                y_lo, y_hi = min(y_lo, y), max(y_hi, y)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx]:
                        visited[ny][nx] = True
                        pr, pg, pb, pa = px[nx, ny]
                        if pa >= 8 and min(pr, pg, pb) >= 238 and (max(pr, pg, pb) - min(pr, pg, pb)) <= 10:
                            stack.append((nx, ny))
            if min(x_hi - x_lo + 1, y_hi - y_lo + 1) <= max_thickness:
                for x, y in comp:
                    px[x, y] = (0, 0, 0, 0)
    return im


def cutout(im, mode="auto"):
    if mode == "alpha":
        return im
    if mode == "white":
        return remove_white_gaps(cutout_white(im))
    if mode == "auto":
        if is_white_background(im):
            return remove_white_gaps(cutout_white(im))
        try:
            return remove_white_gaps(cutout_rembg(im))
        except RuntimeError:
            raise
    raise ValueError(f"未知抠图模式：{mode}")


def trim_and_normalize(im, target_h=TARGET_H):
    """裁掉透明边，缩放到统一高度。"""
    bbox = im.getbbox()
    if bbox is None:
        raise RuntimeError("抠图后是空的，检查照片是否只剩背景，或换 --cutout 模式")
    im = im.crop(bbox)
    w, h = im.size
    if h <= 0 or w <= 0:
        raise RuntimeError("抠图结果尺寸异常")
    new_w = max(1, round(w * target_h / h))
    return im.resize((new_w, target_h), Image.LANCZOS)


def decontaminate(im):
    """对白底做去混合，消除缩放后残留的白边。"""
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if 0 < a < 255:
                t = a / 255.0
                if a < 40:
                    px[x, y] = (0, 0, 0, 0)
                    continue
                nr = (r - 255 * (1 - t)) / t
                ng = (g - 255 * (1 - t)) / t
                nb = (b - 255 * (1 - t)) / t
                px[x, y] = (int(max(0, min(255, nr))), int(max(0, min(255, ng))),
                            int(max(0, min(255, nb))), a)
    return im


def premult_resize(im, height):
    """预乘 alpha 缩放：黑底/白底各合成一次再解出颜色与 alpha，避免边缘发黑。"""
    w0, h0 = im.size
    nw = max(1, round(w0 * height / h0))
    black = Image.alpha_composite(Image.new("RGBA", im.size, (0, 0, 0, 255)), im)
    white = Image.alpha_composite(Image.new("RGBA", im.size, (255, 255, 255, 255)), im)
    b_img = black.resize((nw, height), Image.LANCZOS)
    w_img = white.resize((nw, height), Image.LANCZOS)
    bp, wp = b_img.load(), w_img.load()
    out = Image.new("RGBA", (nw, height))
    op = out.load()
    for y in range(height):
        for x in range(nw):
            br, bg, bb, _ = bp[x, y]
            wr, wg, wb, _ = wp[x, y]
            a = 255 - max(wr - br, wg - bg, wb - bb)
            if a < 6:
                op[x, y] = (0, 0, 0, 0)
                continue
            t = a / 255.0
            op[x, y] = (int(max(0, min(255, br / t))), int(max(0, min(255, bg / t))),
                        int(max(0, min(255, bb / t))), a)
    return out


# ---------------- 视图推导 ----------------

def make_side(front):
    """侧面近似：横向压到 82% 并轻微旋转，做出转身感。"""
    w, h = front.size
    squeezed = front.resize((max(1, round(w * 0.82)), h), Image.LANCZOS)
    rotated = squeezed.rotate(-4.0, resample=Image.BICUBIC, expand=False,
                             fillcolor=(0, 0, 0, 0))
    bbox = rotated.getbbox() or (0, 0, rotated.width, rotated.height)
    rotated = rotated.crop(bbox)
    if rotated.height != h:
        rotated = rotated.resize((max(1, round(rotated.width * h / rotated.height)), h),
                                 Image.LANCZOS)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.paste(rotated, ((w - rotated.width) // 2, h - rotated.height), rotated)
    return canvas


def make_back(front):
    """背面近似：水平镜像并轻微压暗。"""
    return ImageEnhance.Brightness(front.transpose(Image.FLIP_LEFT_RIGHT)).enhance(0.92)


# ---------------- 锚点推断 ----------------

def _row_extents(im):
    """逐行求 alpha 内容的左右边界。"""
    w, h = im.size
    px = im.load()
    left, right = [], []
    for y in range(h):
        lo, hi = None, None
        for x in range(w):
            if px[x, y][3] > 8:
                if lo is None:
                    lo = x
                hi = x
        left.append(lo)
        right.append(hi)
    return left, right


def _smooth(values, radius=3):
    out = []
    for i in range(len(values)):
        window = [v for v in values[max(0, i - radius): i + radius + 1] if v is not None]
        out.append(sum(window) / len(window) if window else None)
    return out


def _column_runs(im, y_lo, y_hi):
    """在给定行区间内统计每列是否有内容，返回连续区段列表 [(x_lo, x_hi), ...]。"""
    w, _ = im.size
    px = im.load()
    cover = [0] * w
    for y in range(max(0, y_lo), min(im.height, y_hi + 1)):
        for x in range(w):
            if px[x, y][3] > 8:
                cover[x] += 1
    runs, start = [], None
    for x in range(w):
        if cover[x] > 0 and start is None:
            start = x
        elif cover[x] == 0 and start is not None:
            if x - start >= 3:
                runs.append((start, x - 1))
            start = None
    if start is not None and w - start >= 3:
        runs.append((start, w - 1))
    return runs


def infer_anchors(im):
    """从 alpha 剪影推断身体锚点，全部用比例量，换体型自动适配。

    肩线取剪影最宽的一行（对多数角色，肩/手臂同时展开处就是最宽处）；
    双脚取底部区间的左右两个着地区段。
    """
    w, h = im.size
    left, right = _row_extents(im)
    rows = [i for i in range(h) if left[i] is not None]
    if not rows:
        raise RuntimeError("剪影为空，无法推断锚点")
    top, bottom = rows[0], rows[-1]
    body_h = max(1, bottom - top + 1)

    widths = [None if left[i] is None else right[i] - left[i] + 1 for i in range(h)]
    smooth_w = _smooth(widths)

    # 肩线：25%~80% 高度范围内最宽的一行
    lo = top + int(0.25 * body_h)
    hi = top + int(0.80 * body_h)
    candidates = [(smooth_w[y], y) for y in range(lo, hi + 1) if smooth_w[y] is not None]
    shoulder_y = max(candidates)[1] if candidates else top + int(0.50 * body_h)

    arm_y = min(bottom, shoulder_y + int(0.06 * body_h))
    row_l = left[arm_y] if left[arm_y] is not None else min(x for x in left if x is not None)
    row_r = right[arm_y] if right[arm_y] is not None else max(x for x in right if x is not None)
    row_w = max(1, row_r - row_l)

    arm_left = row_l + int(0.10 * row_w)
    arm_right = row_r - int(0.10 * row_w)
    pivot_left = row_l + int(0.28 * row_w)
    pivot_right = row_r - int(0.28 * row_w)

    # 双脚：底部 8% 区间的着地区段
    band_lo = bottom - int(0.08 * body_h)
    runs = _column_runs(im, band_lo, bottom)
    if len(runs) >= 2:
        lo_run, hi_run = runs[0], runs[-1]
        foot_left = (lo_run[0] + lo_run[1]) / 2.0
        foot_right = (hi_run[0] + hi_run[1]) / 2.0
        foot_rx = max(8.0, 0.30 * max(hi_run[1] - hi_run[0], lo_run[1] - lo_run[0]))
    elif len(runs) == 1:
        rl, rr = runs[0]
        span = rr - rl
        foot_left = rl + 0.30 * span
        foot_right = rr - 0.30 * span
        foot_rx = max(8.0, 0.22 * span)
    else:
        foot_left, foot_right = 0.30 * w, 0.70 * w
        foot_rx = 0.18 * w

    return {
        "w": w, "h": h,
        "top": top, "bottom": bottom, "body_h": body_h,
        "shoulder_y": shoulder_y,
        "arm_y": arm_y,
        "arm_left": arm_left, "arm_right": arm_right,
        "pivot_left": pivot_left, "pivot_right": pivot_right,
        "arm_rx": 0.18 * row_w, "arm_ry": 0.15 * body_h,
        "foot_y": bottom - int(0.05 * body_h),
        "foot_pivot_y": bottom - int(0.10 * body_h),
        "foot_left": foot_left, "foot_right": foot_right,
        "foot_rx": foot_rx, "foot_ry": 0.05 * body_h,
    }


# ---------------- 舞蹈烘焙 ----------------

def _bilinear(px, w, h, x, y):
    """对 RGBA 做预乘 alpha 的双线性采样。"""
    if x < 0:
        x = 0.0
    elif x > w - 1:
        x = float(w - 1)
    if y < 0:
        y = 0.0
    elif y > h - 1:
        y = float(h - 1)
    x0, y0 = int(x), int(y)
    x1, y1 = min(x0 + 1, w - 1), min(y0 + 1, h - 1)
    fx, fy = x - x0, y - y0
    w00 = (1 - fx) * (1 - fy)
    w10 = fx * (1 - fy)
    w01 = (1 - fx) * fy
    w11 = fx * fy
    p00 = px[x0, y0]
    p10 = px[x1, y0]
    p01 = px[x0, y1]
    p11 = px[x1, y1]
    a = (p00[3] * w00 + p10[3] * w10 + p01[3] * w01 + p11[3] * w11) / 255.0
    if a <= 1e-6:
        return (0, 0, 0, 0)
    r = (p00[0] * p00[3] * w00 + p10[0] * p10[3] * w10
         + p01[0] * p01[3] * w01 + p11[0] * p11[3] * w11) / (a * 255.0)
    g = (p00[1] * p00[3] * w00 + p10[1] * p10[3] * w10
         + p01[1] * p01[3] * w01 + p11[1] * p11[3] * w11) / (a * 255.0)
    b = (p00[2] * p00[3] * w00 + p10[2] * p10[3] * w10
         + p01[2] * p01[3] * w01 + p11[2] * p11[3] * w11) / (a * 255.0)
    return (int(max(0, min(255, r))), int(max(0, min(255, g))),
            int(max(0, min(255, b))), int(max(0, min(255, a * 255))))


def warp_frame(src, phase, a, eyes=None, limb_scale=1.0):
    """按比例锚点生成一帧舞蹈。坐标全部来自 anchors，换角色自动适配。"""
    w, h = src.size
    px = src.load()
    body_h = a["body_h"]
    s = math.sin(phase * 2.0)
    s1 = math.sin(phase)
    s2 = math.sin(phase * 4.0)
    bob = abs(math.sin(phase * 2.0)) * 0.012 * body_h
    sway_amp = 0.020 * w * s1
    sway_y0 = a["top"] + 0.62 * body_h

    arm_rad_sin = math.sin(math.radians(-16.0 * s * limb_scale - 3.0 * s2))
    arm_rad_cos = math.cos(math.radians(-16.0 * s * limb_scale - 3.0 * s2))
    arm_lift = 0.030 * body_h * max(0.0, s) * limb_scale
    arm_rx = max(4.0, a["arm_rx"])
    arm_ry = max(4.0, a["arm_ry"])
    arm_inv_rx2 = 1.0 / (arm_rx * arm_rx)
    arm_inv_ry2 = 1.0 / (arm_ry * arm_ry)

    foot_lift_l = 0.024 * body_h * max(0.0, s) * limb_scale
    foot_lift_r = 0.024 * body_h * max(0.0, -s) * limb_scale
    foot_rx = max(4.0, a["foot_rx"])
    foot_ry = max(4.0, a["foot_ry"])
    foot_inv_rx2 = 1.0 / (foot_rx * foot_rx)
    foot_inv_ry2 = 1.0 / (foot_ry * foot_ry)
    foot_rad = math.radians(2.5 * s * limb_scale)

    blink = 0.0
    if eyes:
        blink = max(0.0, math.sin(phase)) ** 6

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    op = out.load()
    for y in range(h):
        for x in range(w):
            dx = sway_amp * min(1.0, max(0.0, (sway_y0 - y) / max(1.0, sway_y0)))
            dy = bob

            # 手臂（左右各一条，绕肩摆动）
            for cx, pivot, sign in ((a["arm_left"], a["pivot_left"], -1.0),
                                    (a["arm_right"], a["pivot_right"], 1.0)):
                wt = math.exp(-2.0 * ((x - cx) ** 2 * arm_inv_rx2
                                      + (y - a["arm_y"]) ** 2 * arm_inv_ry2))
                if wt < 1e-4:
                    continue
                rx = (x - pivot) * arm_rad_cos - (y - a["shoulder_y"]) * arm_rad_sin + pivot
                ry = (x - pivot) * arm_rad_sin + (y - a["shoulder_y"]) * arm_rad_cos + a["shoulder_y"]
                dx += wt * (rx - x)
                dy += wt * (ry - y)
                dy -= wt * arm_lift * (1.0 if sign > 0 else 0.0)

            # 鞋子（左右交替抬起）
            for cx, lift in ((a["foot_left"], foot_lift_l), (a["foot_right"], foot_lift_r)):
                wt = math.exp(-2.0 * ((x - cx) ** 2 * foot_inv_rx2
                                      + (y - a["foot_y"]) ** 2 * foot_inv_ry2))
                if wt < 1e-4:
                    continue
                rx = (x - cx) * math.cos(foot_rad) - (y - a["foot_pivot_y"]) * math.sin(foot_rad) + cx
                ry = (x - cx) * math.sin(foot_rad) + (y - a["foot_pivot_y"]) * math.cos(foot_rad) + a["foot_pivot_y"]
                dx += wt * (rx - x)
                dy += wt * (ry - y) + wt * lift

            # 眨眼（仅在给了眼睛坐标时启用）
            if eyes and blink > 0.02:
                for ex, ey in eyes:
                    wt = math.exp(-2.0 * (((x - ex) / max(3.0, 0.075 * w)) ** 2
                                          + ((y - ey) / max(3.0, 0.035 * body_h)) ** 2))
                    if wt > 1e-4:
                        dy += (ey - y) * blink * wt * 0.8

            op[x, y] = _bilinear(px, w, h, x - dx, y - dy)
    return out


def make_dance(front, anchors, frames=FRAMES, eyes=None):
    return [warp_frame(front, 2.0 * math.pi * i / frames, anchors, eyes=eyes) for i in range(frames)]


def preview_sheet(frames, cell_max=(134, 238)):
    """棋盘格预览拼图（按实际缩略图尺寸排版，避免裁切）。"""
    thumbs = []
    for frame in frames:
        thumb = frame.copy()
        thumb.thumbnail(cell_max, Image.LANCZOS)
        thumbs.append(thumb)
    cols = 4
    rows = (len(thumbs) + cols - 1) // cols
    pad = 8
    cell_w = max(t.width for t in thumbs) + pad
    cell_h = max(t.height for t in thumbs) + pad
    board_w = cols * cell_w + pad
    board_h = rows * cell_h + pad
    board = Image.new("RGB", (board_w, board_h), (255, 0, 255))
    d = ImageDraw.Draw(board)
    for y in range(0, board_h, 16):
        for x in range(0, board_w, 16):
            if ((x // 16) + (y // 16)) % 2 == 0:
                d.rectangle([x, y, x + 15, y + 15], fill=(0, 170, 0))
    for i, thumb in enumerate(thumbs):
        cx = pad + (i % cols) * cell_w + (cell_w - pad - thumb.width) // 2
        cy = pad + (i // cols) * cell_h + (cell_h - pad - thumb.height) // 2
        board.paste(thumb, (cx, cy), thumb)
    return board


# ---------------- 打包 ----------------

def parse_eyes(text):
    if not text:
        return None
    parts = [float(v) for v in text.replace(" ", "").split(",")]
    if len(parts) != 4:
        raise ValueError("--eyes 需要 x1,y1,x2,y2 四个数")
    return [(parts[0], parts[1]), (parts[2], parts[3])]


def write_pet_launcher(out_dir):
    """Write a Windows launcher that finds the portable pet executable nearby."""
    launcher = os.path.join(out_dir, "启动桌宠.bat")
    with open(launcher, "w", encoding="ascii", newline="\r\n") as f:
        f.write(
            "@echo off\n"
            "setlocal\n"
            'set "ASSET_DIR=%~dp0"\n'
            'set "PET_EXE="\n'
            'for %%E in ("%~dp0*.exe" "%~dp0..\\*.exe") do (\n'
            '  if exist "%%~fE" if not defined PET_EXE set "PET_EXE=%%~fE"\n'
            ")\n"
            'if not defined PET_EXE (\n'
            "  echo Cannot find the desktop pet program.\n"
            "  echo Extract the Windows portable version beside this asset folder.\n"
            "  pause\n"
            "  exit /b 1\n"
            ")\n"
            'start "" "%PET_EXE%" --assets "%ASSET_DIR%"\n'
        )


def build(photo_path, name, out_dir, cutout_mode="auto", frames=FRAMES,
          eyes=None, expressions_dir=None, write_preview=True, lines=None):
    src = load_photo(photo_path)
    cut = cutout(src, cutout_mode)
    front = decontaminate(trim_and_normalize(cut))
    side = make_side(front)
    back = make_back(front)

    sprite_dir = os.path.join(out_dir, "sprites")
    dance_dir = os.path.join(out_dir, "assets", "dance")
    expr_dir = os.path.join(out_dir, "assets", "expressions")
    for d in (sprite_dir, dance_dir):
        os.makedirs(d, exist_ok=True)

    views = {"front": front, "side": side, "back": back}
    sizes = {m: round(TARGET_H * m) for m in SIZE_LEVELS.values()}
    for key, im in views.items():
        im.save(os.path.join(sprite_dir, f"{key}.png"), optimize=True)
        for height in sizes.values():
            premult_resize(im, height).save(
                os.path.join(sprite_dir, f"{key}_{height}.png"), optimize=True)
        # 清掉上一次生成留下的、尺寸档位已经不再使用的精灵
        keep = {f"{key}.png"} | {f"{key}_{h}.png" for h in sizes.values()}
        for fn in os.listdir(sprite_dir):
            if fn.startswith(f"{key}_") and fn not in keep:
                os.remove(os.path.join(sprite_dir, fn))

    icon = premult_resize(front, 64)
    square = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    square.paste(icon, ((64 - icon.width) // 2, (64 - icon.height) // 2), icon)
    square.save(os.path.join(sprite_dir, "icon.png"))

    anchors = infer_anchors(front)
    dance = make_dance(front, anchors, frames=frames, eyes=eyes)
    for i, frame in enumerate(dance):
        frame.save(os.path.join(dance_dir, f"front_{i:02d}.png"), optimize=True)

    if expressions_dir and os.path.isdir(expressions_dir):
        os.makedirs(expr_dir, exist_ok=True)
        for fn in sorted(os.listdir(expressions_dir)):
            if not fn.lower().endswith((".png", ".webp", ".jpg", ".jpeg", ".bmp")):
                continue
            stem = os.path.splitext(fn)[0]
            im = decontaminate(trim_and_normalize(
                cutout(load_photo(os.path.join(expressions_dir, fn)), "white")))
            if im.height != 340:
                im = premult_resize(im, 340)
            im.save(os.path.join(expr_dir, f"{stem}.png"), optimize=True)

    if isinstance(lines, str):
        lines = lines.splitlines()
    dialogue = [str(line).strip() for line in (lines or []) if str(line).strip()]
    cfg = {
        "name": name,
        "lines": dialogue,
        "asset_dir": ".",
        "size_levels": SIZE_LEVELS,
        "frames": frames,
    }
    with open(os.path.join(out_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    write_pet_launcher(out_dir)

    if write_preview:
        preview_sheet(dance).save(os.path.join(out_dir, "preview.png"))
        front.save(os.path.join(out_dir, "sprite_preview.png"))

    return {
        "out_dir": out_dir,
        "sprite_size": front.size,
        "anchors": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in anchors.items()},
        "frames": len(dance),
        "has_side": os.path.exists(os.path.join(sprite_dir, "side.png")),
        "has_back": os.path.exists(os.path.join(sprite_dir, "back.png")),
        "expressions": len(os.listdir(expr_dir)) if os.path.isdir(expr_dir) else 0,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="一张照片生成桌宠素材包")
    ap.add_argument("--photo", required=True, help="输入照片（png/jpg，建议单主体、背景干净）")
    ap.add_argument("--name", default="我的桌宠", help="桌宠显示名称")
    ap.add_argument("--out", default=None, help="输出目录，默认 pets/<name>")
    ap.add_argument("--cutout", choices=["auto", "white", "alpha"], default="auto",
                    help="抠图模式：auto=白底优先、否则 rembg；white=强制白底；alpha=已是透明图")
    ap.add_argument("--frames", type=int, default=FRAMES, help="舞蹈帧数，默认 16")
    ap.add_argument("--eyes", default=None, help="眼睛坐标 x1,y1,x2,y2（可选，启用眨眼）")
    ap.add_argument("--expressions", default=None, help="可选：白底表情图片目录")
    ap.add_argument("--no-preview", action="store_true", help="不生成预览图")
    args = ap.parse_args(argv)

    out = args.out or os.path.join("pets", args.name)
    report = build(
        args.photo, args.name, out,
        cutout_mode=args.cutout, frames=args.frames,
        eyes=parse_eyes(args.eyes), expressions_dir=args.expressions,
        write_preview=not args.no_preview,
    )
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
