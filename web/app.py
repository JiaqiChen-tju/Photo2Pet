# -*- coding: utf-8 -*-
"""本地网页版：浏览器里上传一张照片，生成素材包并下载 zip。

只用标准库（http.server + zipfile），不依赖 Flask；生成逻辑复用 make_pet.py。

用法：
    python web/app.py                # 打开 http://127.0.0.1:8000
    python web/app.py --port 8123    # 指定端口
    python web/app.py --no-browser   # 不自动开浏览器
"""
import argparse
import base64
import io
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote
from urllib.request import build_opener, ProxyHandler


def _configure_console():
    """Avoid UnicodeEncodeError on non-UTF-8 consoles (e.g. English Windows)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


_configure_console()

BUNDLE_ROOT = getattr(sys, "_MEIPASS", None)
if getattr(sys, "frozen", False) and BUNDLE_ROOT:
    ROOT = BUNDLE_ROOT
    WEB_DIR = os.path.join(ROOT, "web")
else:
    WEB_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT = os.path.dirname(WEB_DIR)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import make_pet  # noqa: E402

PAGE_PATH = os.path.join(WEB_DIR, "index.html")
WORK_ROOT = os.path.join(ROOT, ".tmp", "web")
MAX_UPLOAD = 20 * 1024 * 1024          # 单张图片上限 20MB
MAX_REQUEST = 100 * 1024 * 1024        # 照片、表情和表单总计 100MB
MAX_EXPRESSIONS = 20
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
EXPRESSION_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
BUILD_LOCK = threading.Lock()
DOWNLOAD_CACHE_LOCK = threading.Lock()
DOWNLOAD_CACHE = {}
DOWNLOAD_CACHE_TTL = 15 * 60
MAX_CACHED_DOWNLOADS = 3


def parse_multipart(body, boundary):
    """把 multipart/form-data 解析成 {字段名: 文本或字节}。"""
    fields, files = {}, {}
    sep = b"--" + boundary
    for part in body.split(sep):
        if not part or part.strip() in (b"", b"--", b"--\r\n"):
            continue
        part = part[2:] if part.startswith(b"\r\n") else part
        if b"\r\n\r\n" not in part:
            continue
        head, data = part.split(b"\r\n\r\n", 1)
        if data.endswith(b"\r\n"):
            data = data[:-2]
        name = re.search(rb'name="([^"]*)"', head)
        filename = re.search(rb'filename="([^"]*)"', head)
        if not name:
            continue
        key = name.group(1).decode("utf-8", "replace")
        if filename:
            files[key] = (filename.group(1).decode("utf-8", "replace"), data)
        else:
            fields[key] = data.decode("utf-8", "replace")
    return fields, files


def safe_stem(name, fallback="pet"):
    """把用户输入的名字变成能安全放进 zip 文件名的短串。"""
    name = (name or "").strip()
    keep = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name).strip("_")
    return keep[:32] or fallback


def safe_expression_filename(filename):
    """移除上传文件名中的路径和不适合作为菜单名的字符。"""
    basename = os.path.basename(filename.replace("\\", "/"))
    stem, ext = os.path.splitext(basename)
    ext = ext.lower()
    if ext not in EXPRESSION_EXT:
        raise ValueError(f"不支持的表情图片格式：{ext or '未知'}")
    stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", stem).strip("_")
    if not stem:
        raise ValueError("表情图片文件名不能为空")
    return stem + ext


def build_pack(photo_bytes, filename, name, frames, cutout, eyes,
               lines=None, expression_files=None):
    """生成素材包，返回 zip 字节、下载名、报告和内嵌预览图。"""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(f"不支持的图片格式：{ext or '未知'}（请用 png/jpg/webp）")

    os.makedirs(WORK_ROOT, exist_ok=True)
    work = tempfile.mkdtemp(prefix="upload_", dir=WORK_ROOT)
    try:
        src = os.path.join(work, "upload" + ext)
        with open(src, "wb") as f:
            f.write(photo_bytes)
        out = os.path.join(work, "pack")
        expr_dir = None
        if expression_files:
            expr_dir = os.path.join(work, "expressions")
            os.makedirs(expr_dir)
            saved_names = set()
            for expression_name, expression_data in expression_files:
                safe_name = safe_expression_filename(expression_name)
                key = safe_name.casefold()
                if key in saved_names:
                    raise ValueError(f"表情图片文件名重复：{os.path.splitext(safe_name)[0]}")
                saved_names.add(key)
                if len(expression_data) > MAX_UPLOAD:
                    raise ValueError(f"表情图片超过 20MB：{safe_name}")
                with open(os.path.join(expr_dir, safe_name), "wb") as f:
                    f.write(expression_data)
        display_name = (name or "").strip() or "我的桌宠"
        report = make_pet.build(
            src, display_name, out,
            cutout_mode=cutout, frames=frames,
            eyes=make_pet.parse_eyes(eyes) if eyes else None,
            expressions_dir=expr_dir, write_preview=True, lines=lines)

        previews = {}
        for preview_name, key in (
                ("sprite_preview.png", "sprite_preview"),
                ("preview.png", "dance_preview")):
            with open(os.path.join(out, preview_name), "rb") as f:
                previews[key] = "data:image/png;base64," + base64.b64encode(
                    f.read()).decode("ascii")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for base, _, fns in os.walk(out):
                for fn in sorted(fns):
                    full = os.path.join(base, fn)
                    arc = os.path.relpath(full, out).replace(os.sep, "/")
                    zf.write(full, arc)
        stem = safe_stem(display_name)
        return buf.getvalue(), f"{stem}-素材包.zip", report, previews
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cache_download(blob, filename):
    now = time.monotonic()
    with DOWNLOAD_CACHE_LOCK:
        expired = [key for key, value in DOWNLOAD_CACHE.items()
                   if value[0] <= now]
        for key in expired:
            del DOWNLOAD_CACHE[key]
        while len(DOWNLOAD_CACHE) >= MAX_CACHED_DOWNLOADS:
            del DOWNLOAD_CACHE[next(iter(DOWNLOAD_CACHE))]
        token = secrets.token_urlsafe(24)
        DOWNLOAD_CACHE[token] = (now + DOWNLOAD_CACHE_TTL, blob, filename)
    return token


class Handler(BaseHTTPRequestHandler):
    server_version = "Photo2Pet/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, body, ctype="text/plain; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            try:
                with open(PAGE_PATH, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, "index.html 缺失".encode("utf-8"))
        elif path == "/healthz":
            self._json(200, {"ok": True, "app": "Photo2Pet web"})
        elif path.startswith("/api/download/"):
            token = path.removeprefix("/api/download/")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
                self._json(404, {"ok": False, "error": "下载链接无效或已过期"})
                return
            with DOWNLOAD_CACHE_LOCK:
                entry = DOWNLOAD_CACHE.get(token)
                if entry and entry[0] <= time.monotonic():
                    del DOWNLOAD_CACHE[token]
                    entry = None
            if not entry:
                self._json(404, {"ok": False, "error": "下载链接无效或已过期，请重新生成"})
                return
            _, blob, download_name = entry
            self._send_download(blob, download_name)
        else:
            self._send(404, "not found".encode("utf-8"))

    def _send_download(self, blob, download_name):
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header(
            "Content-Disposition",
            "attachment; filename=\"pet-pack.zip\"; filename*=UTF-8''%s"
            % quote(download_name))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(blob)

    def do_POST(self):
        if self.path.split("?")[0] != "/api/build":
            self._send(404, "not found".encode("utf-8"))
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            self._json(400, {"ok": False, "error": "请求体为空"})
            return
        if length > MAX_REQUEST:
            self._json(413, {"ok": False, "error": "上传内容过大（总上限 100MB）"})
            return

        ctype = self.headers.get("Content-Type", "")
        m = re.search(r"boundary=([^;]+)", ctype)
        if not m:
            self._json(400, {"ok": False, "error": "缺少 multipart 边界"})
            return
        body = self.rfile.read(length)
        fields, files = parse_multipart(body, m.group(1).strip('"').encode())

        if "photo" not in files:
            self._json(400, {"ok": False, "error": "没有收到照片"})
            return
        fname, data = files["photo"]
        if len(data) > MAX_UPLOAD:
            self._json(413, {"ok": False, "error": "照片太大了（上限 20MB）"})
            return
        expression_entries = sorted(
            (key, value) for key, value in files.items()
            if re.fullmatch(r"expression_\d+", key)
        )
        if len(expression_entries) > MAX_EXPRESSIONS:
            self._json(400, {"ok": False, "error": f"表情图片最多上传 {MAX_EXPRESSIONS} 张"})
            return
        expression_files = [value for _, value in expression_entries]
        if any(len(image_data) > MAX_UPLOAD for _, image_data in expression_files):
            self._json(413, {"ok": False, "error": "单张表情图片不能超过 20MB"})
            return
        if sum(len(image_data) for _, image_data in expression_files) + len(data) > MAX_REQUEST:
            self._json(413, {"ok": False, "error": "上传内容过大（总上限 100MB）"})
            return

        name = (fields.get("name") or "").strip()[:24]
        try:
            frames = int(fields.get("frames") or 16)
        except ValueError:
            frames = 16
        frames = max(4, min(32, frames))
        cutout = fields.get("cutout") or "auto"
        if cutout not in ("auto", "white", "alpha"):
            cutout = "auto"
        eyes = (fields.get("eyes") or "").strip()
        lines = [line.strip() for line in (fields.get("lines") or "").splitlines()
                 if line.strip()]

        try:
            with BUILD_LOCK:
                blob, download_name, report, previews = build_pack(
                    data, fname, name, frames, cutout, eyes, lines, expression_files)
        except ValueError as e:
            self._json(400, {"ok": False, "error": str(e)})
            return
        except Exception:
            traceback.print_exc()
            self._json(500, {"ok": False, "error": "生成失败，看看控制台里的报错"})
            return

        token = cache_download(blob, download_name)
        self._json(200, {
            "ok": True,
            "download_url": "/api/download/" + token,
            "filename": download_name,
            "sprite_size": "%dx%d" % tuple(report["sprite_size"]),
            "frames": report["frames"],
            "expressions": report["expressions"],
            "zip_size": len(blob),
            "previews": previews,
        })
        self.log_message("packed %s (%d bytes) anchor=%s", download_name,
                         len(blob), report["anchors"])


def smoke_test():
    if not os.path.isfile(PAGE_PATH):
        raise FileNotFoundError(f"生成器页面缺失：{PAGE_PATH}")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        opener = build_opener(ProxyHandler({}))
        with opener.open(base + "/healthz", timeout=5) as response:
            health = json.loads(response.read().decode("utf-8"))
        if not health.get("ok"):
            raise RuntimeError("生成器健康检查失败")
        with opener.open(base + "/", timeout=5) as response:
            page = response.read().decode("utf-8")
        if 'id="pet-result-preview"' not in page:
            raise RuntimeError("生成器页面预览控件缺失")
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join()
    print(json.dumps({
        "ok": True,
        "frozen": bool(getattr(sys, "frozen", False)),
        "page": True,
    }, ensure_ascii=True), flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Photo2Pet 本地网页版")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--smoke-test", action="store_true")
    args = ap.parse_args(argv)

    if args.smoke_test:
        smoke_test()
        return

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{srv.server_address[1]}/"
    print(f"Serving on {url}  (Ctrl+C to stop)", flush=True)
    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(0.8), webbrowser.open(url)),
                         daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("bye")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
