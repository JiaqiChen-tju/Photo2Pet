# -*- coding: utf-8 -*-
"""make_pet.py 的单元测试：只用标准库 unittest，本地不需要装 pytest。

运行：python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw

import make_pet

# 测试临时目录固定放在仓库内的 .tmp/ 下（已被 gitignore）。
# 不用 tempfile 的默认目录：某些受限环境里 %TEMP% 不可写，tempfile 会静默回落到当前目录，
# 把临时文件漏进仓库。
TMP_BASE = os.environ.get("PET_TEST_TMP") or os.path.join(ROOT, ".tmp", "tests")
os.makedirs(TMP_BASE, exist_ok=True)


def new_tmp(prefix):
    return tempfile.mkdtemp(prefix=prefix, dir=TMP_BASE)


def make_subject(path, size=(200, 300), gap=True):
    """画一个白底测试角色：躯干 + 两条腿 + 封住腿缝的鞋子。"""
    w, h = size
    im = Image.new("RGB", size, (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.ellipse([60, 10, 140, 90], fill=(90, 140, 200))          # 头
    d.rounded_rectangle([40, 80, 160, 200], radius=20, fill=(70, 110, 180))  # 躯干
    d.rounded_rectangle([70, 190, 92, 268], radius=8, fill=(40, 60, 120))    # 左腿
    d.rounded_rectangle([108, 190, 130, 268], radius=8, fill=(40, 60, 120))  # 右腿
    if gap:
        d.rectangle([70, 262, 130, 280], fill=(200, 60, 60))   # 鞋子，把腿缝封住
    else:
        d.rectangle([84, 190, 116, 265], fill=(40, 60, 120))   # 实心，无腿缝
    im.save(path)
    return path


def count_near_white_opaque(im, alpha_min=200, light_min=238):
    """数一数「不透明且接近纯白」的像素（测试图都很小，直接逐点扫）。"""
    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    n = 0
    for y in range(h):
        for x in range(w):
            p = px[x, y]
            if p[3] >= alpha_min and min(p[:3]) >= light_min:
                n += 1
    return n


def make_face(path, size=(120, 120)):
    """白底小图：一个圆脸 + 两点眼睛，用来测表情图处理。"""
    w, h = size
    im = Image.new("RGB", size, (255, 255, 255))
    d = ImageDraw.Draw(im)
    r = int(min(w, h) * 0.35)
    cx, cy = w // 2, h // 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(250, 200, 120))
    d.ellipse([cx - r // 2, cy - r // 4, cx - r // 4, cy + r // 8], fill=(40, 40, 40))
    d.ellipse([cx + r // 4, cy - r // 4, cx + r // 2, cy + r // 8], fill=(40, 40, 40))
    im.save(path)
    return path


class CutoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = new_tmp("pet_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_white_background_is_opaque_source(self):
        path = make_subject(os.path.join(self.tmp, "subject.png"))
        self.assertTrue(make_pet.is_white_background(make_pet.load_photo(path)))

    def test_cutout_removes_background(self):
        path = make_subject(os.path.join(self.tmp, "subject.png"))
        cut = make_pet.cutout(make_pet.load_photo(path), "white")
        # 四个角必须是透明的，主体中心必须不透明
        for xy in [(0, 0), (cut.width - 1, 0), (0, cut.height - 1)]:
            self.assertEqual(cut.getpixel(xy)[3], 0)
        self.assertGreater(cut.getpixel((cut.width // 2, cut.height // 3))[3], 200)

    def test_remove_white_gaps_clears_enclosed_gap(self):
        path = make_subject(os.path.join(self.tmp, "subject.png"))
        cut = make_pet.cutout_white(make_pet.load_photo(path))
        self.assertGreater(count_near_white_opaque(cut), 0)   # 腿缝被鞋子封住，泛洪进不去

        cleared = make_pet.remove_white_gaps(cut)
        self.assertEqual(count_near_white_opaque(cleared), 0)

    def test_remove_white_gaps_keeps_wide_white_area(self):
        """宽大的白色主体不该被当成缝隙删掉。"""
        im = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rectangle([5, 5, 115, 115], fill=(30, 30, 30, 255))
        d.rectangle([40, 20, 80, 100], fill=(255, 255, 255, 255))  # 40px 宽白衣服
        out = make_pet.remove_white_gaps(im)
        self.assertGreater(count_near_white_opaque(out), 1000)

    def test_alpha_mode_is_noop(self):
        im = Image.new("RGBA", (10, 10), (255, 255, 255, 255))
        self.assertIs(make_pet.cutout(im, "alpha"), im)


class AnchorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = new_tmp("pet_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _front(self, gap=True, size=(200, 300), name="subject.png"):
        path = make_subject(os.path.join(self.tmp, name), size=size, gap=gap)
        cut = make_pet.cutout(make_pet.load_photo(path), "white")
        return make_pet.trim_and_normalize(cut)

    def test_anchors_inside_body(self):
        front = self._front()
        a = make_pet.infer_anchors(front)
        self.assertGreaterEqual(a["shoulder_y"], int(a["top"] + 0.25 * a["body_h"]))
        self.assertLessEqual(a["shoulder_y"], int(a["top"] + 0.80 * a["body_h"]))
        self.assertLess(a["arm_left"], a["pivot_left"])
        self.assertLess(a["pivot_left"], a["pivot_right"])
        self.assertLess(a["pivot_right"], a["arm_right"])
        self.assertLess(a["foot_left"], a["foot_right"])
        self.assertGreater(a["arm_rx"], 0)
        self.assertGreater(a["foot_rx"], 0)

    def test_anchors_scale_with_wide_and_narrow_bodies(self):
        """不同宽高比的角色都应该给出可用的锚点，而不是贴边或越界。"""
        for size in [(120, 400), (320, 260)]:
            front = self._front(size=size, name=f"s{size[0]}.png")
            a = make_pet.infer_anchors(front)
            self.assertGreater(a["arm_left"], 0)
            self.assertLess(a["arm_right"], a["w"])
            self.assertGreater(a["foot_y"], a["shoulder_y"])


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = new_tmp("pet_build_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_writes_complete_package(self):
        photo = make_subject(os.path.join(self.tmp, "subject.png"))
        out = os.path.join(self.tmp, "pet")
        report = make_pet.build(photo, "测试仔", out, frames=4, eyes=False)

        sprite_dir = os.path.join(out, "sprites")
        for key in ("front", "side", "back"):
            self.assertTrue(os.path.isfile(os.path.join(sprite_dir, f"{key}.png")))
            for m in make_pet.SIZE_LEVELS.values():
                self.assertTrue(os.path.isfile(
                    os.path.join(sprite_dir, f"{key}_{round(make_pet.TARGET_H * m)}.png")))
        self.assertTrue(os.path.isfile(os.path.join(sprite_dir, "icon.png")))

        dance_dir = os.path.join(out, "assets", "dance")
        frames = sorted(os.listdir(dance_dir))
        self.assertEqual(len(frames), 4)
        self.assertEqual(frames[0], "front_00.png")

        with open(os.path.join(out, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["name"], "测试仔")
        self.assertEqual(cfg["frames"], 4)
        self.assertEqual(cfg["asset_dir"], ".")
        self.assertEqual(cfg["size_levels"], make_pet.SIZE_LEVELS)
        self.assertEqual(cfg["lines"], [])
        launcher_path = os.path.join(out, "启动桌宠.bat")
        self.assertTrue(os.path.isfile(launcher_path))
        with open(launcher_path, encoding="ascii") as f:
            launcher = f.read()
        self.assertIn('--assets "%ASSET_DIR%"', launcher)
        self.assertIn('"%~dp0..\\*.exe"', launcher)
        self.assertIn('if /I not "%%~nE"=="Photo2Pet-Generator"', launcher)

        self.assertTrue(os.path.isfile(os.path.join(out, "preview.png")))
        self.assertEqual(report["frames"], 4)
        self.assertEqual(report["sprite_size"][1], make_pet.TARGET_H)

    def test_preview_checkerboard_uses_neutral_colors(self):
        frame = Image.new("RGBA", (30, 60), (20, 40, 60, 255))
        preview = make_pet.preview_sheet([frame])
        colors = preview.getcolors(preview.width * preview.height)
        self.assertIn((245, 247, 245), [color for _, color in colors])
        self.assertIn((225, 232, 226), [color for _, color in colors])

    def test_build_is_idempotent(self):
        photo = make_subject(os.path.join(self.tmp, "subject.png"))
        out = os.path.join(self.tmp, "pet")
        make_pet.build(photo, "a", out, frames=3, eyes=False, write_preview=False)
        first = sorted(os.listdir(os.path.join(out, "sprites")))
        make_pet.build(photo, "b", out, frames=3, eyes=False, write_preview=False)
        self.assertEqual(first, sorted(os.listdir(os.path.join(out, "sprites"))))

    def test_build_with_expressions(self):
        photo = make_subject(os.path.join(self.tmp, "subject.png"))
        expr_src = os.path.join(self.tmp, "expr")
        os.makedirs(expr_src)
        make_face(os.path.join(expr_src, "开心.png"))
        out = os.path.join(self.tmp, "pet")
        report = make_pet.build(photo, "a", out, frames=2, eyes=False,
                                expressions_dir=expr_src, write_preview=False)
        self.assertEqual(report["expressions"], 1)
        self.assertTrue(os.path.isfile(os.path.join(out, "assets", "expressions", "开心.png")))

    def test_build_preserves_custom_dialogue_without_defaults(self):
        photo = make_subject(os.path.join(self.tmp, "subject.png"))
        out = os.path.join(self.tmp, "pet")
        lines = ["第一句", "", "第二句", "第三句"]
        make_pet.build(photo, "台词测试", out, frames=2, eyes=False,
                       write_preview=False, lines=lines)
        with open(os.path.join(out, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["lines"], ["第一句", "第二句", "第三句"])


if __name__ == "__main__":
    unittest.main()
