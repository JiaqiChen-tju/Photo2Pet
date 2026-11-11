# -*- coding: utf-8 -*-
"""离屏渲染一张桌宠预览，方便检查表情缩放、底边对齐、透明效果。"""
import argparse
import importlib.util
import os
import sys

from PIL import Image, ImageDraw

from PySide6.QtWidgets import QApplication

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE, "logs")


def load_app():
    spec = importlib.util.spec_from_file_location("kugua_pet_app", os.path.join(BASE, "桌宠.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checkerboard(size):
    w, h = size
    board = Image.new("RGB", (w, h), (255, 0, 255))
    draw = ImageDraw.Draw(board)
    s = 20
    for y in range(0, h, s):
        for x in range(0, w, s):
            if ((x // s) + (y // s)) % 2 == 0:
                draw.rectangle([x, y, x + s - 1, y + s - 1], fill=(0, 190, 0))
    return board


def save_dance_sheet(window, app, style):
    """用已烘焙的舞蹈帧拼成 4x4 姿态预览图。"""
    dance_dir = os.path.join(BASE, "assets", "dance")
    frames = []
    for index in range(16):
        path = os.path.join(dance_dir, f"front_{index:02d}.png")
        if not os.path.isfile(path):
            continue
        frame = Image.open(path).convert("RGBA")
        frame.thumbnail((134, 238), Image.LANCZOS)
        frames.append(frame)
    if not frames:
        print("no dance frames")
        return

    cols, rows = 4, 4
    pad = 8
    cell_w = max(frame.width for frame in frames)
    cell_h = max(frame.height for frame in frames)
    board = checkerboard((cols * (cell_w + pad) + pad, rows * (cell_h + pad) + pad))
    for index, frame in enumerate(frames):
        col = index % cols
        row = index // cols
        x = pad + col * (cell_w + pad) + (cell_w - frame.width) // 2
        y = pad + row * (cell_h + pad) + (cell_h - frame.height) // 2
        board.paste(frame, (x, y), frame)
    out = os.path.join(LOG_DIR, "dance_sheet.png")
    board.save(out)
    print(f"dance sheet: {out}")
    print(f"dance style: {style}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expression", default="", help="表情文件名（不含扩展名）；留空用第一张")
    parser.add_argument("--out", default=os.path.join(LOG_DIR, "pet_preview.png"))
    parser.add_argument("--dance-sheet", action="store_true", help="输出一个舞蹈周期的姿态预览")
    parser.add_argument("--dance-style", type=int, default=1, choices=(0, 1, 2))
    args = parser.parse_args()

    app = QApplication(sys.argv)
    mod = load_app()
    window = mod.PetWindow()
    window.show()
    app.processEvents()

    if args.dance_sheet:
        os.makedirs(LOG_DIR, exist_ok=True)
        save_dance_sheet(window, app, args.dance_style)
        window.hide()
        return

    items = window._expression_files()
    selected = None
    if items:
        if args.expression:
            selected = next((item for item in items if item[0] == args.expression), items[0])
        else:
            selected = items[0]
        window.set_custom_expression(selected[1])
        window.t = 50
        window.banner_start = 0.0
        window.banner_until = 10.0
        app.processEvents()

    os.makedirs(LOG_DIR, exist_ok=True)
    raw_path = os.path.join(LOG_DIR, "pet_preview_raw.png")
    window.grab().save(raw_path)

    im = Image.open(raw_path).convert("RGBA")
    board = checkerboard(im.size)
    board.paste(im, (0, 0), im)
    board.save(args.out)

    print(f"preview: {args.out}")
    if selected:
        print(f"expression: {selected[0]}")
    window.hide()


if __name__ == "__main__":
    main()
