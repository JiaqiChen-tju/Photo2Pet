# 开发、测试与发版

## 环境

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

`requirements.txt` 是运行和生成素材所需的全部依赖（PySide6、psutil、nvidia-ml-py、Pillow；
`nvidia-ml-py` 的 Python 模块名是 `pynvml`）；`requirements-dev.txt` 只额外加 PyInstaller（打包用）。

## 代码地图

| 位置 | 干什么 |
|------|--------|
| `桌宠.py` | 全部运行时逻辑：窗口、动作、气泡、菜单、自检。一个文件，故意不拆包 |
| `make_pet.py` | 照片 → 素材包：抠图、归一化、三视图、锚点推断、舞蹈帧、预览 |
| `tools/make_demo_assets.py` | 重新生成原创通用示例角色、表情、精灵与舞蹈帧 |
| `tools/render_preview.py` | 离屏渲染桌宠/舞蹈预览，用来检查显示效果 |
| `tools/build_exe.ps1` | 打包 Windows 单文件 exe（`.bat` 是双击入口） |
| `web/app.py` + `web/index.html` | 本机网页版，复用 `make_pet.build()` |
| `tests/` | unittest，覆盖素材生成、运行时与网页接口 |
| `.github/workflows/ci.yml` | Windows + Python 3.12 跑单测与离屏自检 |
| `.github/workflows/release.yml` | `v*` tag 触发打包并挂 Release |

两个核心文件都用**纯 Pillow / 纯 PySide6**，没有 numpy、scipy、rembg 依赖——
这是刻意的：新克隆仓库的人 `pip install -r requirements.txt` 就能跑。

## 跑测试

```bash
python -m unittest discover -s tests -v
```

- Windows 无桌面会话时要 `QT_QPA_PLATFORM=offscreen`（CI 里就是这么设的）。
- 测试临时文件写在仓库 `.tmp/` 下（已 gitignore）。**不要**用 `tempfile` 的默认目录：
  受限环境里 `%TEMP%` 可能不可写，`tempfile` 会静默回落到当前目录，把临时文件漏进仓库。
- 单测不含 pytest，故意保持"零额外依赖"，方便任何人 clone 下来直接跑。

三块测试分别盯：

| 文件 | 重点 |
|------|------|
| `tests/test_make_pet.py` | 白底抠图、被前景包住的白色空腔清理、宽大白面不误删、锚点合理性、`build()` 产物完整性与幂等 |
| `tests/test_pet_runtime.py` | `--assets` 两种写法、配置合并优先级、素材根解析、离屏 `--smoke-test` |
| `tests/test_web.py` | 起真实 HTTP 服务，走一遍上传 → 生成 → 下载，含 400/413 的失败路径 |

## 自检

```bash
python 桌宠.py --smoke-test
```

离屏跑一遍真实渲染，检查精灵是否齐全、表情能否切换锁定、舞蹈帧数、气泡是否正常，
结果写 `smoke_report.json`。这是"改完代码有没有把界面搞坏"的最快信号。

## 打包

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\build_exe.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\build_exe.ps1 -Name 我的桌宠
```

四步：刷新图标 → 自检 → 单元测试 → PyInstaller。产物 `dist\<名字>.exe`（默认 `Photo2Pet.exe`），
并把 `使用说明.txt`、`README.md` 一起复制进 `dist`。

两个已知坑：

- **脚本必须存成带 BOM 的 UTF-8**。Windows PowerShell 5.1 读无 BOM 的 UTF-8 会按 ANSI 解析，
  中文文件名直接变乱码（`桌宠.py` → `妗屽疇.py`），打包第一步就失败。
- PyInstaller onefile 在 `%TEMP%` 不可写时**启动阶段**就挂（`Could not create temporary directory`），
  而且 GUI 版没控制台，看起来只是"进程卡住"。排查时先把 `$env:TEMP` 指到可写目录再跑。

## 发版

1. 改 `README.md` 的已知限制/参数表（如果有变化）。
2. 跑一遍测试与自检，`tools/build_exe.ps1` 能出产物。
3. 打 tag：

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

   `release.yml` 会自动打包 `dist/<仓库名>.exe`、压成 `<仓库名>-portable.zip`、
   上传 artifact 并挂 Release（release notes 自动生成）。

产物名来自 `github.event.repository.name`，所以仓库名字就是 exe 名字；
`release.yml` 会将同一名称用于 exe 和便携 zip。

## 首次公开前检查

- **示例素材**：确认默认角色仍由仓库内的原创生成脚本制作，且没有混入未经许可的第三方角色图、表情包或截图；新增第三方素材时先确认授权并更新 `NOTICE`。
- **依赖许可**：核对 `NOTICE` 中第三方组件与实际打包内容一致，并检查 PySide6/Qt 的 LGPL 要求以及随 Release 分发时需要附带的许可材料。
- **历史与内容**：检查所有将要推送的提交信息/邮箱、历史文件、截图、日志和配置；不要只检查当前工作树。不要上传个人照片、生成素材包、令牌或本机路径。
- **干净环境复验**：按 README 从新克隆创建虚拟环境、安装依赖、运行单测和离屏自检；再实际启动一次桌宠并用示例图片走完生成流程。
- **Release 验收**：推送版本 tag 后，检查 GitHub Actions 成功；下载便携 zip 和 `.sha256` 文件，验证哈希并确认压缩包中有 exe、使用说明、README、LICENSE 和 NOTICE。
- **仓库设置**：确认默认分支与 CI 触发分支一致，并允许 Release workflow 写入 Releases；保护默认分支并启用 Issues/Discussions（按项目需要）。

## 提交规范

- 一个 PR / 一次提交只做一件事，提交信息写"改了什么、为什么"，不要写"update"。
- 动了 `make_pet.py` 的锚点或尺寸逻辑，必须同时跑三种体型的实跑（宽窄各一张）并对比 `preview.png`。
- 动了 `桌宠.py` 的路径解析，`tests/test_pet_runtime.py` 必须跟着改。
