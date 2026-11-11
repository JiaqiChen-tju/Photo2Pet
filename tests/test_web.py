# -*- coding: utf-8 -*-
"""web/app.py 的接口测试：起一个真实 HTTP 服务，走一遍上传 → 生成 → 下载。

运行：python -m unittest discover -s tests -v
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "web", "app.py")

TMP_BASE = os.environ.get("PET_TEST_TMP") or os.path.join(ROOT, ".tmp", "tests")
os.makedirs(TMP_BASE, exist_ok=True)

BOUNDARY = "----photo2petTestBoundary"


def build_body(fields, files):
    """按 multipart 规范拼请求体（文件部分保持二进制）。"""
    chunks = []
    for k, v in fields.items():
        chunks.append(
            f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n".encode()
            + str(v).encode("utf-8") + b"\r\n")
    for k, (fname, data) in files.items():
        chunks.append(
            (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"{k}\"; "
             f"filename=\"{fname}\"\r\nContent-Type: image/png\r\n\r\n").encode()
            + data + b"\r\n")
    chunks.append(f"--{BOUNDARY}--\r\n".encode())
    return b"".join(chunks)


def make_photo(path):
    """白底小人，腿缝被鞋子封住（顺带覆盖白缝清理）。"""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (240, 360), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.ellipse([80, 20, 160, 100], fill=(90, 140, 200))
    d.rounded_rectangle([55, 90, 185, 250], radius=24, fill=(70, 110, 180))
    d.rounded_rectangle([90, 240, 112, 322], radius=9, fill=(40, 60, 120))
    d.rounded_rectangle([128, 240, 150, 322], radius=9, fill=(40, 60, 120))
    d.rectangle([90, 314, 150, 336], fill=(200, 60, 60))
    im.save(path)
    return path


class WebAppTest(unittest.TestCase):
    proc = None
    base = None

    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen(
            [sys.executable, APP, "--port", "0", "--no-browser"],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        deadline = time.time() + 20
        while time.time() < deadline:
            line = cls.proc.stdout.readline()
            if not line:
                break
            m = re.search(r"Serving on (http://[\d.]+:\d+/)", line)
            if m:
                cls.base = m.group(1).rstrip("/")
                break
        if not cls.base:
            cls.proc.kill()
            raise RuntimeError("网页服务没起来")

    @classmethod
    def tearDownClass(cls):
        if cls.proc and cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()

    def _post(self, fields, files):
        body = build_body(fields, files)
        req = urllib.request.Request(
            self.base + "/api/build", data=body, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"})
        return urllib.request.urlopen(req, timeout=180)

    def test_index_page(self):
        with urllib.request.urlopen(self.base + "/", timeout=20) as r:
            html = r.read().decode("utf-8")
        self.assertEqual(r.status, 200)
        self.assertIn("生成你的桌宠", html)
        self.assertIn("/api/build", html)
        self.assertIn("给你的桌宠定制台词吧", html)
        self.assertIn('id="expressions"', html)
        self.assertIn("multiple hidden", html)
        self.assertIn("从图片左上角开始", html)
        self.assertIn("启动桌宠.bat", html)

    def test_healthz(self):
        with urllib.request.urlopen(self.base + "/healthz", timeout=20) as r:
            data = json.loads(r.read().decode())
        self.assertTrue(data["ok"])

    def test_upload_builds_downloadable_pack(self):
        tmp = tempfile.mkdtemp(prefix="web_", dir=TMP_BASE)
        photo = make_photo(os.path.join(tmp, "p.png"))
        with open(photo, "rb") as f:
            data = f.read()
        resp = self._post(
            {"name": "网页测试", "frames": "8", "cutout": "auto",
             "lines": "第一句\n\n第二句\n第三句"},
            {"photo": ("p.png", data),
             "expression_0": ("开心.png", data),
             "expression_1": ("惊讶.png", data)})
        self.assertEqual(resp.status, 200)
        self.assertIn("application/zip", resp.headers["Content-Type"])
        self.assertEqual(resp.headers["X-Pet-Frames"], "8")
        blob = resp.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = zf.namelist()
            self.assertIn("sprites/front.png", names)
            self.assertIn("sprites/side.png", names)
            self.assertIn("sprites/back.png", names)
            self.assertIn("sprites/icon.png", names)
            self.assertIn("sprites/front_238.png", names)
            self.assertIn("preview.png", names)
            self.assertIn("启动桌宠.bat", names)
            self.assertIn("assets/expressions/开心.png", names)
            self.assertIn("assets/expressions/惊讶.png", names)
            dance = [n for n in names if n.startswith("assets/dance/front_")]
            self.assertEqual(len(dance), 8)
            cfg = json.loads(zf.read("config.json").decode("utf-8"))
            self.assertEqual(cfg["name"], "网页测试")
            self.assertEqual(cfg["frames"], 8)
            self.assertEqual(cfg["asset_dir"], ".")
            self.assertEqual(cfg["lines"], ["第一句", "第二句", "第三句"])
            self.assertEqual(resp.headers["X-Pet-Expressions"], "2")

    def test_upload_without_custom_content_has_no_old_dialogue_or_expressions(self):
        tmp = tempfile.mkdtemp(prefix="web_empty_", dir=TMP_BASE)
        photo = make_photo(os.path.join(tmp, "p.png"))
        with open(photo, "rb") as f:
            data = f.read()
        resp = self._post({"name": "无自定义内容"}, {"photo": ("p.png", data)})
        with zipfile.ZipFile(io.BytesIO(resp.read())) as zf:
            cfg = json.loads(zf.read("config.json").decode("utf-8"))
            self.assertEqual(cfg["lines"], [])
            self.assertFalse(any(n.startswith("assets/expressions/") for n in zf.namelist()))

    def test_missing_photo_is_rejected(self):
        body = build_body({"name": "空"}, {})
        req = urllib.request.Request(
            self.base + "/api/build", data=body, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"})
        with self.assertRaises(urllib.request.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=60)
        self.assertEqual(ctx.exception.code, 400)
        payload = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("没有收到照片", payload["error"])

    def test_bad_format_is_rejected(self):
        body = build_body({}, {"photo": ("a.gif", b"GIF89a-fake")})
        req = urllib.request.Request(
            self.base + "/api/build", data=body, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"})
        with self.assertRaises(urllib.request.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=60)
        self.assertEqual(ctx.exception.code, 400)
        payload = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("不支持的图片格式", payload["error"])


if __name__ == "__main__":
    unittest.main()
