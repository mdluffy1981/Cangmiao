# Cangmiao（苍妙）

**一款面向 Windows 的围棋人机对弈与 AI 分析桌面应用。**

Cangmiao 将围棋棋盘、对局管理和 KataGo AI 分析整合在一个简洁的桌面界面中。你可以选择棋盘大小和规则，与 AI 进行对弈；也可以进入分析模式，自由摆放黑白双方的着手，观察 AI 对局势的判断和候选变化。

项目使用 Python 和 PySide6 构建桌面界面，KataGo 作为独立进程运行，并通过 GTP 协议通信。Windows 安装包提供标准 CPU、Tiny CPU 和 NVIDIA CUDA 版本；CPU 版开箱即用，CUDA 版面向 NVIDIA GPU，已内置 CUDA 12.5 / cuDNN 9 运行库，只需 NVIDIA 显卡和较新的驱动。

## 功能一览

- **人机对弈：** 支持 9 路、13 路和 19 路棋盘，可选择执黑或执白。执白时 AI 执黑先行。
- **可调 AI 强度：** 提供快速、标准、较强、最强等预设，以搜索访问数和时间预算控制对弈强度。预设不是固定段位，也不是硬实时保证。
- **自由分析棋局：** 在分析模式中按顺序操作黑白双方，落子或悔棋后可继续分析新局面；分析会持续运行，直到手动停止或切换模式。
- **死活题练习：** 从左侧进入死活题模式，导入包含答案变化分支的 SGF 题集，逐题练习、查看提示或预览答案；做题进度保存在本机。程序不内置第三方题库，判题依赖 SGF 提供的答案分支。
- **候选着法与局势评估：** 查看候选点、双方胜率、目差、访问数、搜索用时和 NPS，并在棋盘上预览候选变化。候选点以颜色区分最优解、本手和其他候选。
- **常用对局操作：** 支持悔棋、停一手、认输；双方连续停一手后可由引擎计分。
- **棋谱管理：** 打开和导出 SGF 棋谱，兼容 UTF-8 和 GB18030 编码的棋谱。
- **多种规则：** 支持中国、日本、韩国、AGA、新西兰和 Tromp-Taylor 规则，以及自定义贴目。
- **CPU 或 GPU 引擎：** 可使用 OpenCL 或 NVIDIA CUDA GPU 引擎，也可使用 AVX2 或通用 CPU 引擎。CPU 版无需独立安装 Python；CUDA 版已内置 CUDA/cuDNN 运行库，无需另外安装。
- **中英文界面：** 支持简体中文和 English 界面。

## 界面介绍

程序启动后直接进入棋盘工作区。界面围绕棋盘、模式切换和侧边控制面板组织：

1. **棋盘与主菜单** — 棋盘是主要操作区域；左侧主菜单用于切换“人机对战”“AI 分析”和“死活题”，并标示当前模式。
2. **对局控制面板** — 新建棋局、设置执棋方、棋盘大小、规则、贴目和 AI 强度；对局中可执行 AI 落子、悔棋、停一手、认输和数子等操作。
3. **分析面板** — 展示胜率、目差和搜索信息，并列出推荐着法。选择候选着法可在棋盘上预览变化。
4. **着手列表** — 查看棋局着手记录。打开棋谱后可继续浏览、对弈或分析。
5. **死活题面板** — 导入含解答分支的 SGF 题集，选择题目后可重做、查看提示或预览答案；错误或正确记录保存在本地应用目录。
6. **可折叠侧栏** — 可收起控制面板以扩大棋盘区域；收起侧栏不会自动停止正在进行的分析。
7. **引擎状态与设置** — 首次使用时按提示配置引擎；引擎状态、启动进度和错误信息会在界面中反馈。

分析模式会持续搜索并消耗 CPU/GPU 资源。搜索初期的胜率和候选评估可能波动；不需要分析时请停止搜索。

## 下载与安装

### Windows 安装包（推荐）

前往 [GitHub Releases](https://github.com/mdluffy1981/Cangmiao/releases) 下载适合自己的版本。通常选择名称中带有 `Setup.exe` 的安装程序；如果下载 ZIP，请先解压，再按压缩包说明运行其中的安装程序。ZIP 包不是免安装的绿色便携版。

标准 CPU 版包含 KataGo CPU 引擎、模型和应用运行环境。安装后无需单独安装 Python，也不需要为内置 CPU 引擎另外下载文件。安装程序默认以当前 Windows 用户安装，通常不需要管理员权限。

如果 Release 同时提供不同引擎版本，可按硬件和下载需求选择：

- **标准 CPU 版：** 包含通用 CPU 引擎，并可包含 AVX2 优化引擎；支持 AVX2 时可使用相应版本。
- **Tiny CPU 版：** 体积更小，使用通用 CPU 引擎和较小的 KataGo 模型；适合优先考虑下载体积的用户。
- **CUDA 版：** 面向 NVIDIA GPU，包含 CUDA KataGo 引擎及 NVIDIA CUDA 12.5 / cuDNN 9.8 运行库（cuBLAS、NVRTC、cuDNN），无需另外安装 CUDA Toolkit 或 cuDNN，只需支持 CUDA 12.5 的 NVIDIA 驱动。安装包体积较大，详情见安装目录 `engine\CUDA-NOTICE.txt`。

CPU 引擎在复杂局面上的搜索速度通常低于 GPU。没有 NVIDIA 显卡时，可选择标准 CPU 版或 OpenCL GPU 引擎。

### 从源码运行

需要 Windows 10/11 64 位和 Python 3.10 或更新版本。克隆或下载本仓库后，在项目目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
```

配置 KataGo 引擎（选择一种后端）：

```powershell
# GPU（OpenCL，需兼容的显卡驱动）
.\.venv\Scripts\python -m katago_gui.setup_engine --backend opencl

# NVIDIA GPU（CUDA；自动下载 CUDA/cuDNN 运行库，只需显卡驱动）
.\.venv\Scripts\python -m katago_gui.setup_engine --backend cuda

# CPU（通用，兼容性优先）
.\.venv\Scripts\python -m katago_gui.setup_engine --backend eigen

# CPU（需要支持 AVX2 的处理器）
.\.venv\Scripts\python -m katago_gui.setup_engine --backend eigenavx2
```

首次配置会下载引擎和模型，因此需要网络连接。之后可从开始菜单启动，或在项目目录运行：

```powershell
.\.venv\Scripts\python -m katago_gui
```

详细安装、引擎配置和构建说明请参阅 [README.md](README.md)。

## 快速上手

1. **启动程序。** 安装版从开始菜单启动；源码版按上面的命令运行。
2. **首次配置引擎。** 如果应用提示尚未配置 KataGo，打开“引擎设置”；也可以使用自动配置命令。使用内置 CPU 安装包的用户通常无需此步骤。
3. **新建棋局。** 选择 9 路、13 路或 19 路棋盘，设置执黑或执白、规则和贴目，并选择 AI 强度。
4. **开始对弈。** 在棋盘交叉点落子；轮到 AI 时等待其应手。也可使用悔棋、停一手或认输等控制。
5. **分析棋局。** 切换到“AI 分析”，在棋盘上编辑双方着手，启动分析后查看胜率、候选着法和搜索数据。完成后手动停止分析。
6. **保存或继续棋谱。** 使用打开/导出 SGF 功能保存棋局，或从已有棋谱继续分析。

打开 SGF 后，程序会进入分析模式，便于检查和延续棋局。AI 分析不受人机对弈强度预设的搜索预算限制，且会持续搜索；长时间分析会增加资源占用。

## 项目优势

- **下载后即可体验：** CPU 安装包包含运行环境、引擎和模型，减少初次安装配置步骤。
- **对弈与复盘兼顾：** 人机模式适合实战，分析模式允许自由编辑双方着手，适合复盘和研究变化。
- **信息直观可探索：** 候选点直接显示在棋盘上，并提供胜率、目差和搜索信息；选择候选即可预览变化。
- **配置选择灵活：** 根据硬件和偏好使用 CPU 或 OpenCL GPU 引擎，也可选择不同棋盘、规则和贴目。
- **以本地桌面应用为主：** KataGo 在本机作为独立进程运行；程序设置和日志保存在本地。内置模型无需在每次启动时联网获取。
- **面向日常使用：** 支持常用对局操作和 SGF 棋谱，侧栏可折叠，并提供中英文界面。

> **性能提示：** CPU 版开箱即用，但思考速度受处理器性能和模型影响。AI 分析会持续占用计算资源；不使用时请停止分析。AI 强度预设用于控制对弈搜索预算，不代表固定棋力等级。

## 致谢

- 感谢 **KataGo** 项目及其开发者和贡献者，提供强大的围棋引擎。访问 [KataGo GitHub](https://github.com/lightvector/KataGo)。
- 感谢 **KataGo Training** 及模型训练贡献者提供公开的围棋模型。访问 [KataGo Training](https://katagotraining.org/networks/)。
- 感谢 **Python**、**PySide6 / Qt** 及相关开源社区提供项目所依赖的语言、界面框架和工具。

KataGo 引擎、围棋模型、PySide6/Qt 及其他依赖各自遵循其上游许可。使用或再分发随安装包提供的第三方组件时，请查阅相应项目的许可和说明文件。

---

# Cangmiao

**A Windows desktop application for playing Go against AI and analyzing Go positions.**

Cangmiao brings a Go board, game controls, and KataGo analysis together in a desktop interface. Play a game against AI with your preferred board size and rules, or switch to analysis mode to explore moves for both sides and review KataGo's evaluations and candidate variations.

The interface is built with Python and PySide6. KataGo runs as a separate process and communicates with the application through the GTP protocol. Windows CPU installers bundle the engine and model for a simpler first-run experience. You can also configure a compatible OpenCL GPU engine.

## Features

- **Play against AI:** Choose a 9x9, 13x13, or 19x19 board and play as Black or White. When playing White, AI makes the first move as Black.
- **Adjustable AI strength:** Choose from several presets that control search visits and time. Presets are not fixed rank equivalents or hard real-time guarantees.
- **Explore positions:** Play moves for either side in analysis mode. Analysis can continue after moves or undo operations until you stop it or switch modes.
- **Life & death practice:** Import SGF collections with solution variations, practice problems, request hints, and preview answers. Progress is stored locally. No third-party puzzle collection is bundled; judging follows the solution variations in the SGF.
- **Detailed analysis:** Review candidate moves, both sides' win rates, score lead, visits, search time, and NPS. Candidate variations can be previewed on the board and are visually categorized.
- **Game controls:** Undo, pass, resign, and score the game after both sides pass.
- **SGF support:** Open and export SGF records, including records encoded in UTF-8 or GB18030.
- **Multiple rules:** Chinese, Japanese, Korean, AGA, New Zealand, and Tromp-Taylor rules, with configurable komi.
- **CPU and GPU engines:** Configure an OpenCL GPU engine or an AVX2 or generic CPU engine. The CPU installer does not require a separate Python installation.
- **Bilingual interface:** Switch between Simplified Chinese and English.

## Interface

The application opens directly to the board workspace:

1. **Board and navigation** — The board is the main play area. The left-side menu switches between Play, AI Analysis, and Life & Death and highlights the active mode.
2. **Game controls** — Create a game, choose board size, color, rules, komi, and AI strength; then make AI moves, undo, pass, resign, or score.
3. **Analysis panel** — View win rates, score lead, search metrics, and candidate moves. Selecting a candidate previews its variation on the board.
4. **Move list** — Follow the game's move history and continue from an opened record.
5. **Life & death panel** — Import SGF collections with solution variations, choose a problem, and restart, request a hint, or preview the answer. Results are saved locally.
6. **Collapsible sidebar** — Hide the controls to give the board more room. Collapsing the sidebar does not stop ongoing analysis.
7. **Engine status and settings** — Configure KataGo when needed; startup progress, engine status, and errors are reported in the interface.

Analysis searches continuously and consumes CPU/GPU resources. Early win-rate and candidate estimates can fluctuate; stop analysis when it is no longer needed.

## Download and installation

### Windows installer (recommended)

Visit [GitHub Releases](https://github.com/mdluffy1981/Cangmiao/releases) and choose a release. For a typical installation, download the asset whose name ends in `Setup.exe`. If you download a ZIP archive, extract it and follow the included instructions to run its installer. The ZIP package is not a portable, no-install application.

The standard CPU installer bundles KataGo, a model, and the application runtime. Python does not need to be installed separately, and the bundled CPU engine does not need an additional download. By default, the installer installs for the current Windows user and usually does not require administrator privileges.

If both standard and Tiny CPU builds are available:

- **Standard CPU build:** Includes a generic CPU engine and may also include an AVX2-optimized engine for supported processors.
- **Tiny CPU build:** Smaller download using a generic CPU engine and a smaller KataGo model; choose it when package size is the priority.

CPU search is generally slower than GPU search, especially in complex positions. For extended, intensive analysis, consider configuring a compatible OpenCL GPU engine.

### Run from source

Requires 64-bit Windows 10/11 and Python 3.10 or later. Clone or download this repository, open PowerShell in the project directory, and install the application:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
```

Configure one KataGo backend:

```powershell
# GPU (OpenCL; requires a compatible graphics driver)
.\.venv\Scripts\python -m katago_gui.setup_engine --backend opencl

# CPU (generic; prioritizes compatibility)
.\.venv\Scripts\python -m katago_gui.setup_engine --backend eigen

# CPU (requires an AVX2-capable processor)
.\.venv\Scripts\python -m katago_gui.setup_engine --backend eigenavx2
```

Initial engine setup downloads the engine and model and therefore requires an internet connection. Once configured, launch from the Start menu or run:

```powershell
.\.venv\Scripts\python -m katago_gui
```

See [README.md](README.md) for detailed setup, engine configuration, and build instructions.

## Getting started

1. **Launch the application.** Start it from the Windows Start menu, or use the source command above.
2. **Configure the engine if prompted.** Open Engine Settings or run the setup command. Users of the bundled CPU installer can usually skip this step.
3. **Create a game.** Choose a 9x9, 13x13, or 19x19 board, your color, rules, komi, and an AI strength preset.
4. **Play.** Click an intersection to make a move and wait for AI when it is the engine's turn. Undo, pass, or resign when appropriate.
5. **Analyze.** Switch to AI Analysis, make moves for either side, and start analysis to inspect win rates, candidate moves, and search metrics. Stop the search when finished.
6. **Save or review a record.** Open or export an SGF file to preserve a game or continue analyzing an existing record.

Opening an SGF record enters analysis mode so you can review and extend the game. Unlike AI play, analysis is not limited by the strength preset and continues searching until stopped; long sessions use additional system resources.

## Why Cangmiao

- **Ready to try:** CPU installers bundle the application runtime, engine, and model, reducing initial setup.
- **Play and review in one app:** Use Play mode for games and Analysis mode to edit and study positions for either side.
- **Visual, actionable analysis:** Candidate moves appear on the board alongside win rates, score lead, and search data; select a candidate to preview its variation.
- **Flexible setup:** Choose CPU or OpenCL GPU backends, board sizes, rules, and komi.
- **Local desktop workflow:** KataGo runs as a local process, and application settings and logs are stored locally. The bundled model does not need to be fetched on every launch.
- **Made for everyday Go:** Common game controls, SGF support, a collapsible sidebar, and a bilingual interface are included.

> **Performance note:** The bundled CPU engine works out of the box, but search speed depends on your processor and model. Analysis continuously uses compute resources, so stop it when not needed. AI strength presets control game search budgets and do not represent fixed rank levels.

## Acknowledgements

- Thanks to the **KataGo** project, its developers, and contributors for the Go engine. Visit [KataGo on GitHub](https://github.com/lightvector/KataGo).
- Thanks to **KataGo Training** and the model training contributors for publicly available Go models. Visit [KataGo Training](https://katagotraining.org/networks/).
- Thanks to the **Python**, **PySide6 / Qt**, and broader open-source communities for the language, UI framework, and tools used by this project.

KataGo, Go models, PySide6/Qt, and other dependencies are subject to their respective upstream licenses. Review the applicable license and notices before using or redistributing third-party components bundled with the installers.
