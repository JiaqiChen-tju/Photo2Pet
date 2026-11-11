# -*- coding: utf-8 -*-
"""桌宠.py 的运行时测试：参数解析、配置合并、素材根解析，以及离屏自检。

需要 PySide6；无显示环境时用 QT_QPA_PLATFORM=offscreen。
运行：python -m unittest discover -s tests -v
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PET_PATH = os.path.join(ROOT, "桌宠.py")

# 临时目录固定在仓库 .tmp/ 下（已 gitignore）：受限环境里 %TEMP% 可能不可写，
# tempfile 会静默回落到当前目录，把临时文件漏进仓库。
TMP_BASE = os.environ.get("PET_TEST_TMP") or os.path.join(ROOT, ".tmp", "tests")
os.makedirs(TMP_BASE, exist_ok=True)


def new_tmp(prefix):
    return tempfile.mkdtemp(prefix=prefix, dir=TMP_BASE)


# 无头环境也能 import QtWidgets
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def load_pet_module(argv=None):
    """按文件路径加载 桌宠.py（模块名带中文，不能直接 import）。"""
    old_argv = sys.argv
    sys.argv = list(argv if argv is not None else [PET_PATH])
    try:
        spec = importlib.util.spec_from_file_location("pet_runtime", PET_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.argv = old_argv
    return module


class ArgValueTest(unittest.TestCase):
    def test_defaults_without_args(self):
        pet = load_pet_module()
        self.assertIsNone(pet.arg_value("--assets"))
        self.assertEqual(pet.APP_NAME, pet.DEFAULT_NAME)
        self.assertEqual(pet.PET_LINES, [])
        self.assertEqual(pet.pick_line(), "")
        self.assertEqual(pet.FRAME_COUNT, 16)
        self.assertEqual(pet.SIZE_LEVELS, pet.DEFAULT_SIZE_LEVELS)

    def _arg_value(self, pet, argv, flag):
        old = sys.argv
        sys.argv = list(argv)
        try:
            return pet.arg_value(flag)
        finally:
            sys.argv = old

    def test_space_and_equals_forms(self):
        pet = load_pet_module()
        argv = [PET_PATH, "--assets", "pets/a", "--name=x"]
        self.assertEqual(self._arg_value(pet, argv, "--assets"), "pets/a")
        self.assertEqual(self._arg_value(pet, argv, "--name"), "x")
        self.assertIsNone(self._arg_value(pet, argv, "--frames"))


class AssetResolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = new_tmp("pet_runtime_")
        self.pack = os.path.join(self.tmp, "pack")
        os.makedirs(os.path.join(self.pack, "sprites"))
        os.makedirs(os.path.join(self.pack, "assets", "dance"))
        with open(os.path.join(self.pack, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "包里的小猫", "lines": ["喵"], "frames": 16,
                       "size_levels": {"小": 0.55, "中": 0.7, "大": 0.9}}, f)

    def test_absolute_assets_win_over_local_config(self):
        pet = load_pet_module([PET_PATH, "--assets", self.pack, "--smoke-test"])
        self.assertEqual(os.path.normcase(pet.ASSETS_ROOT), os.path.normcase(self.pack))
        self.assertEqual(pet.APP_NAME, "包里的小猫")
        self.assertEqual(pet.PET_LINES, ["喵"])
        self.assertTrue(os.path.normcase(pet.SPRITE_DIR).startswith(
            os.path.normcase(self.pack)))

    def test_missing_assets_falls_back_to_bundle(self):
        pet = load_pet_module([PET_PATH, "--assets", os.path.join(self.tmp, "nope")])
        self.assertIsNone(pet.ASSETS_ROOT)
        self.assertEqual(pet.APP_NAME, pet.DEFAULT_NAME)
        self.assertEqual(os.path.normcase(pet.SPRITE_DIR),
                         os.path.normcase(os.path.join(pet.BUNDLE_DIR, "sprites")))


class BundledDemoAssetsTest(unittest.TestCase):
    def test_bundled_artwork_is_generic_and_reproducible(self):
        source_dir = os.path.join(ROOT, "assets", "source")
        expression_dir = os.path.join(ROOT, "assets", "expressions")
        self.assertEqual(os.listdir(source_dir), ["mascot.png"])
        self.assertEqual(
            set(os.listdir(expression_dir)),
            {name + ".png" for name in (
                "开心", "期待", "惊讶", "困困", "委屈", "生气", "眨眼", "爱心",
            )},
        )
        self.assertTrue(os.path.isfile(
            os.path.join(ROOT, "tools", "make_demo_assets.py")))


class SmokeTest(unittest.TestCase):
    """离屏跑一遍真实自检，确认精灵、表情、舞蹈都齐。"""

    def setUp(self):
        self.tmp = new_tmp("pet_smoke_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, args=()):
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        proc = subprocess.run(
            [sys.executable, PET_PATH, *args, "--smoke-test"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        report_path = os.path.join(ROOT, "smoke_report.json")
        self.assertTrue(os.path.isfile(report_path), "自检没有写出报告")
        with open(report_path, encoding="utf-8") as f:
            return json.load(f)

    def test_bundled_assets_pass(self):
        report = self._run()
        self.assertTrue(report["ok"], report.get("error", ""))
        self.assertEqual(report["sprites_missing"], [])
        self.assertEqual(report["dance_frames"], 16)

    def test_external_pack_passes_without_expressions(self):
        """素材包里没有表情图时，自检应该仍然通过（菜单显示占位项）。"""
        pack = os.path.join(self.tmp, "mypet")
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "make_pet.py"),
             "--photo", os.path.join(ROOT, "sprites", "front.png"),
             "--name", "外部包", "--out", pack, "--frames", "3",
             "--cutout", "alpha", "--no-preview"],
            cwd=ROOT, capture_output=True, text=True, timeout=300, check=True)
        report = self._run(["--assets", pack])
        self.assertTrue(report["ok"], report.get("error", ""))
        self.assertEqual(report["app_name"], "外部包")
        self.assertEqual(report["expression_count"], 0)
        self.assertEqual(report["dance_frames"], 3)
        self.assertEqual(report["sprites_missing"], [])
        self.assertTrue(os.path.normcase(report["assets_root"]).startswith(
            os.path.normcase(self.tmp)))

    def test_external_pack_with_expression_is_switchable(self):
        import make_pet

        pack = os.path.join(self.tmp, "expression_pack")
        expression_dir = os.path.join(self.tmp, "expressions")
        os.makedirs(expression_dir)
        expression = os.path.join(expression_dir, "用户表情.png")
        with open(os.path.join(ROOT, "assets", "expressions", "开心.png"), "rb") as src:
            with open(expression, "wb") as dst:
                dst.write(src.read())
        make_pet.build(
            os.path.join(ROOT, "assets", "source", "mascot.png"),
            "带表情的桌宠", pack, cutout_mode="alpha", frames=2,
            expressions_dir=expression_dir, write_preview=False,
            lines=["自定义的一句台词", "另一句台词"],
        )
        report = self._run(["--assets", pack])
        self.assertTrue(report["ok"], report.get("error", ""))
        self.assertEqual(report["pet_lines"], ["自定义的一句台词", "另一句台词"])
        self.assertEqual(report["expression_count"], 1)
        self.assertEqual(report["expression_selected"], "用户表情")
        self.assertTrue(report["expression_menu_ok"])
        self.assertTrue(report["expression_menu_selection_ok"])


if __name__ == "__main__":
    unittest.main()
