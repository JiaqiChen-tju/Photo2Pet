# -*- coding: utf-8 -*-
"""从最新精灵生成托盘图标与 Windows ico 图标。"""
import os

from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPRITE_DIR = os.path.join(BASE, "sprites")
SOURCE = os.path.join(SPRITE_DIR, "front_187.png")

if not os.path.isfile(SOURCE):
    raise SystemExit(f"找不到精灵：{SOURCE}")

src = Image.open(SOURCE).convert("RGBA")
src.thumbnail((240, 240), Image.LANCZOS)

canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
canvas.paste(src, ((256 - src.width) // 2, (256 - src.height) // 2), src)
canvas.save(os.path.join(BASE, "icon.ico"),
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

tray = canvas.resize((64, 64), Image.LANCZOS)
tray.save(os.path.join(SPRITE_DIR, "icon.png"))

print("icon.ico 与 sprites/icon.png 已更新")
