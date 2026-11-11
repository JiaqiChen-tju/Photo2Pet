# -*- coding: utf-8 -*-
"""Generate the original, generic demo mascot and its bundled asset pack."""
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
SOURCE_DIR = os.path.join(ROOT, "assets", "source")
TEMP_DIR = os.path.join(ROOT, ".tmp", "demo-assets")
SOURCE_INPUT = os.path.join(TEMP_DIR, "source")
EXPRESSION_INPUT = os.path.join(TEMP_DIR, "expressions")
PACK_DIR = os.path.join(TEMP_DIR, "pack")

EXPRESSIONS = (
    "开心", "期待", "惊讶", "困困", "委屈", "生气", "眨眼", "爱心",
)

INK = (46, 63, 78, 255)
BODY = (246, 202, 126, 255)
BODY_LIGHT = (255, 226, 166, 255)
ACCENT = (67, 159, 157, 255)
CHEEK = (235, 132, 119, 255)
EYE_WHITE = (224, 239, 239, 255)


def draw_mascot(path, expression="开心", white_background=False):
    background = (255, 255, 255, 255) if white_background else (0, 0, 0, 0)
    image = Image.new("RGBA", (320, 480), background)
    draw = ImageDraw.Draw(image)

    def rounded(box, radius, fill, outline=INK, width=5):
        draw.rounded_rectangle(box, radius=radius, fill=fill,
                               outline=outline, width=width)

    def line(points, fill=INK, width=7):
        draw.line(points, fill=fill, width=width, joint="curve")

    line([(160, 48), (160, 28)], ACCENT, 8)
    draw.ellipse((150, 12, 170, 32), fill=CHEEK, outline=INK, width=4)
    rounded((106, 302, 151, 407), 20, ACCENT)
    rounded((169, 302, 214, 407), 20, ACCENT)
    rounded((93, 387, 158, 428), 19, BODY)
    rounded((162, 387, 227, 428), 19, BODY)

    rounded((57, 153, 263, 337), 58, BODY)
    rounded((37, 183, 91, 286), 25, BODY_LIGHT)
    rounded((229, 183, 283, 286), 25, BODY_LIGHT)
    rounded((75, 35, 245, 207), 72, BODY_LIGHT)
    draw.arc((84, 45, 236, 199), 190, 350, fill=ACCENT, width=7)
    draw.ellipse((144, 216, 176, 248), fill=ACCENT)
    draw.ellipse((151, 223, 169, 241), fill=(206, 242, 222, 255))

    if expression == "困困":
        line([(111, 119), (136, 119)], INK, 6)
        line([(184, 119), (209, 119)], INK, 6)
    elif expression == "眨眼":
        draw.ellipse((108, 104, 139, 137), fill=EYE_WHITE, outline=INK, width=4)
        draw.ellipse((181, 104, 212, 137), fill=EYE_WHITE, outline=INK, width=4)
        draw.ellipse((119, 112, 132, 132), fill=INK)
        line([(183, 121), (209, 121)], INK, 6)
    else:
        draw.ellipse((108, 104, 139, 137), fill=EYE_WHITE, outline=INK, width=4)
        draw.ellipse((181, 104, 212, 137), fill=EYE_WHITE, outline=INK, width=4)
        draw.ellipse((119, 112, 132, 132), fill=INK)
        draw.ellipse((192, 112, 205, 132), fill=INK)

    if expression in ("开心", "爱心"):
        draw.arc((128, 128, 192, 177), 5, 175, fill=INK, width=6)
    elif expression == "惊讶":
        draw.ellipse((145, 145, 175, 177), fill=INK)
    elif expression == "困困":
        draw.arc((137, 147, 183, 177), 10, 170, fill=INK, width=6)
    elif expression == "委屈":
        draw.arc((137, 160, 183, 194), 190, 350, fill=INK, width=6)
    elif expression == "生气":
        line([(105, 98), (140, 108)], INK, 6)
        line([(180, 108), (215, 98)], INK, 6)
        draw.arc((137, 160, 183, 194), 190, 350, fill=INK, width=6)
    else:
        draw.arc((137, 146, 183, 184), 5, 175, fill=INK, width=6)

    if expression == "爱心":
        draw.ellipse((83, 145, 101, 163), fill=CHEEK)
        draw.ellipse((219, 145, 237, 163), fill=CHEEK)
    elif expression in ("开心", "期待", "眨眼"):
        draw.ellipse((82, 147, 103, 161), fill=CHEEK)
        draw.ellipse((217, 147, 238, 161), fill=CHEEK)

    if expression == "期待":
        draw.ellipse((229, 52, 261, 84), fill=(255, 213, 91, 255),
                     outline=INK, width=4)

    image.save(path)


def replace_directory(source, destination):
    if os.path.isdir(destination):
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def main():
    if os.path.isdir(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.makedirs(SOURCE_INPUT)
    os.makedirs(EXPRESSION_INPUT)

    mascot_path = os.path.join(SOURCE_INPUT, "mascot.png")
    draw_mascot(mascot_path)
    for expression in EXPRESSIONS:
        draw_mascot(os.path.join(EXPRESSION_INPUT, expression + ".png"),
                    expression, white_background=True)

    import make_pet

    make_pet.build(
        mascot_path, "小伙伴", PACK_DIR,
        cutout_mode="alpha", frames=16,
        expressions_dir=EXPRESSION_INPUT, write_preview=False,
    )

    replace_directory(SOURCE_INPUT, SOURCE_DIR)
    replace_directory(os.path.join(PACK_DIR, "sprites"),
                      os.path.join(ROOT, "sprites"))
    replace_directory(os.path.join(PACK_DIR, "assets", "dance"),
                      os.path.join(ROOT, "assets", "dance"))
    replace_directory(os.path.join(PACK_DIR, "assets", "expressions"),
                      os.path.join(ROOT, "assets", "expressions"))

    subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "make_icon.py")],
        cwd=ROOT, check=True,
    )
    print("Generated generic demo mascot, sprites, expressions, and dance frames.")


if __name__ == "__main__":
    main()
