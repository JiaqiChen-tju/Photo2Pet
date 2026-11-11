# 素材包结构与配置

一次生成产出的目录就叫**素材包**。桌宠程序既可以用它（`--assets`），也可以只把它当参考自己手改。

## 目录长什么样

```
我的桌宠/
├── sprites/
│   ├── front.png            正面原始尺寸（高度 340）
│   ├── side.png             侧面（正面横压 0.82 + 旋转 -4°，近似）
│   ├── back.png             背面（水平镜像 + 亮度 0.92，近似）
│   ├── front_187.png        小档
│   ├── front_238.png        中档
│   ├── front_306.png        大档
│   ├── side_*.png / back_*.png
│   └── icon.png             64×64 图标（透明底）
├── assets/
│   ├── dance/
│   │   └── front_00.png … front_15.png     舞蹈帧（默认 16 帧）
│   └── expressions/                        可选，表情图（没有就显示占位项）
├── config.json
├── 启动桌宠.bat             Windows 便携版启动器
├── preview.png              舞蹈帧拼图（给人看的）
└── sprite_preview.png       正面精灵（给人看的）
```

三档尺寸的名字来自 `round(340 × 档位系数)`，默认系数 `小 0.55 / 中 0.7 / 大 0.9`，
所以是 **187 / 238 / 306**。运行时按同一个公式算文件名，两边必须一致，改系数要同时改两处
（`make_pet.SIZE_LEVELS` 与 `桌宠.py` 的默认值，或者干脆只改 `config.json`）。

## config.json

```json
{
  "name": "我的桌宠",
  "lines": ["用户自定义台词一", "用户自定义台词二"],
  "asset_dir": ".",
  "size_levels": { "小": 0.55, "中": 0.7, "大": 0.9 },
  "frames": 16
}
```

| 字段 | 作用 | 备注 |
|------|------|------|
| `name` | 桌宠显示的名字、`--assets` 时作为身份标识 | 有它才认为这是个"素材包" |
| `lines` | 左键单击时随机冒的台词 | 想改成自己的话就改这里 |
| `asset_dir` | 素材相对路径 | 用 `--assets` 启动时以命令行参数为准 |
| `size_levels` | 三档缩放系数 | 与文件名绑定，见上 |
| `frames` | 舞蹈帧数 | 必须和 `assets/dance/` 里的帧数一致 |

## 桌宠怎么找素材

优先级（`桌宠.py` 里 `_resolve_assets_root()`）：

1. 命令行 `--assets <路径>`：绝对路径直接用；相对路径**先按 exe 所在目录**找，找不到再按当前工作目录找。
2. `config.json` 里的 `asset_dir`。
3. 都没有 → 用 exe 内置的默认精灵。

一旦确定了外部素材包，**精灵、舞蹈、表情全部只从包里读，不做混合**，避免出现"新身体配旧动作"。
网页生成时上传的表情会放在 `assets/expressions/`，右键桌宠并打开「切换表情」即可切换；文件名（不含扩展名）就是菜单显示名称。
Windows 用户可以下载项目 GitHub Releases 中的便携版并解压，再将素材包文件夹放在桌宠程序旁边，双击素材包里的 `启动桌宠.bat` 即可使用该素材包启动，无需输入命令。

## 自己手改素材

想精修某个视图，直接改同名 png 就行，只要满足：

- 画布高度 340，主体底边贴齐，水平居中
- 三档尺寸文件同步存在（或者干脆删掉三档、只用原始尺寸，运行时不会崩）
- 舞蹈帧数量与 `config.json` 的 `frames` 一致

改完跑一次自检确认没漏：

```bash
python 桌宠.py --smoke-test --assets "D:\path\to\我的桌宠"
```

自检报告（`smoke_report.json`）里的 `sprite_dir` / `dance_dir` / `assets_root` 会告诉你
素材实际是从哪里读的，排查"改了没生效"先看这三个字段。

## 用素材包换形象

```bash
# 源码运行
python 桌宠.py --assets "D:\path\to\我的桌宠"

# exe 运行
Photo2Pet.exe --assets "D:\path\to\我的桌宠"
```

把素材包目录和 exe 放在同一层、直接 `Photo2Pet.exe --assets 我的桌宠` 也行（相对路径会先按 exe 目录解析）。
