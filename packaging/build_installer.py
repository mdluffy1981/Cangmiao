"""Build CPU, Tiny, and CUDA Windows installers.

Usage: python packaging\\build_installer.py [--tiny | --cuda] [--skip-test] [--no-installer]

Steps: download/verify the selected KataGo builds and model into build\\cache,
freeze the app with PyInstaller (onedir), bundle the engine under <app>\\engine, smoke-test it,
then compile packaging\\installer.iss with Inno Setup and zip the release into dist\\.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from katago_gui import APP_NAME, __version__  # noqa: E402
from katago_gui import setup_engine as se  # noqa: E402
from katago_gui.bundled import CPU_BACKENDS  # noqa: E402

BUILD = ROOT / "build"
CACHE = BUILD / "cache"
DIST = ROOT / "dist"

# Unofficial Simplified Chinese wizard translation, pinned to the Inno Setup 6.5.4 source tag.
CHINESE_ISL_URL = ("https://raw.githubusercontent.com/jrsoftware/issrc/is-6_5_4/"
                   "Files/Languages/Unofficial/ChineseSimplified.isl")
CHINESE_ISL_SHA256 = "fc1dbf303559cfefd47cf59eec7f1ad1c5fc6266ef8fa64569c13bc754adfeb4"


def fetch_assets(backends: tuple[str, ...] = CPU_BACKENDS, tiny: bool = False) -> dict[str, Path]:
    assets = {}
    for backend in backends:
        url, sha, _ = se.BACKENDS[backend]
        assets[backend] = CACHE / url.rsplit("/", 1)[1]
        se.download(url, assets[backend], sha)
    model_name = se.TINY_MODEL_NAME if tiny else se.MODEL_NAME
    model_url = se.TINY_MODEL_URL if tiny else se.MODEL_URL
    model_sha = se.TINY_MODEL_SHA256 if tiny else se.MODEL_SHA256
    assets["model"] = CACHE / model_name
    se.download(model_url, assets["model"], model_sha)
    return assets


def make_icon(path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPen, QRadialGradient

    _app = QGuiApplication.instance() or QGuiApplication([])
    size = 256
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#d9a95b"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(8, 8, size - 16, size - 16, 40, 40)
    p.setPen(QPen(QColor("#5b3a12"), 6))
    for i in (64, 128, 192):
        p.drawLine(32, i, size - 32, i)
        p.drawLine(i, 32, i, size - 32)
    for center, light, dark in ((QPointF(100, 100), "#666666", "#0a0a0a"), (QPointF(160, 160), "#ffffff", "#c8c8c8")):
        g = QRadialGradient(center - QPointF(18, 18), 70)
        g.setColorAt(0, QColor(light))
        g.setColorAt(1, QColor(dark))
        p.setBrush(QBrush(g))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(center, 52, 52)
    p.end()
    if not img.save(str(path), "ICO"):
        raise SystemExit(f"无法生成图标：{path}")


def freeze(icon: Path) -> Path:
    work, out = BUILD / "pyi-work", BUILD / "pyi-dist"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
                    "--name", APP_NAME, "--icon", str(icon), "--paths", str(ROOT / "src"),
                    "--workpath", str(work), "--distpath", str(out), "--specpath", str(BUILD),
                    str(ROOT / "packaging" / "launcher.py")], check=True)
    return out / APP_NAME


def bundle_engine(app_dir: Path, assets: dict[str, Path], backends: tuple[str, ...] = CPU_BACKENDS,
                  model_name: str = se.MODEL_NAME, tiny: bool = False, cuda: bool = False) -> Path:
    engine = app_dir / "engine"
    shutil.rmtree(engine, ignore_errors=True)
    for backend in backends:
        target = engine / backend
        with zipfile.ZipFile(assets[backend]) as z:
            z.extractall(target)
        exe = next(target.rglob("katago.exe"))
        if exe.parent != target:
            for item in exe.parent.iterdir():
                shutil.move(str(item), target / item.name)
    shutil.copyfile(assets["model"], engine / model_name)
    # The Eigen build's default config already uses CPU-friendly thread defaults.
    config_backend = "eigen" if "eigen" in backends else backends[-1]
    shutil.copyfile(engine / config_backend / "default_gtp.cfg", engine / "gtp.cfg")
    if tiny:
        shutil.copyfile(ROOT / "packaging" / "TINY-MODEL-NOTICE.txt", engine / "MODEL-NOTICE.txt")
    if cuda:
        se.install_cuda_runtime(engine / "cuda", CACHE)
        shutil.copyfile(ROOT / "packaging" / "CUDA-NOTICE.txt", engine / "CUDA-NOTICE.txt")
    return engine


def smoke(engine: Path, backends: tuple[str, ...] = CPU_BACKENDS,
          model_name: str = se.MODEL_NAME) -> None:
    with tempfile.TemporaryDirectory() as home:
        os.environ["KATAGO_GUI_HOME"] = home
        for backend in backends:
            print(f"== 自检 {backend}")
            se.smoke_test(engine / backend / "katago.exe", engine / model_name, engine / "gtp.cfg")


def find_iscc() -> Path:
    candidates = [shutil.which("ISCC.exe")]
    for env, sub in (("LOCALAPPDATA", "Programs"), ("ProgramFiles(x86)", ""), ("ProgramFiles", "")):
        if os.environ.get(env):
            candidates.append(str(Path(os.environ[env], sub, "Inno Setup 6", "ISCC.exe")))
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    raise SystemExit("找不到 Inno Setup 编译器 ISCC.exe；请先运行：winget install JRSoftware.InnoSetup")


def compile_installer(app_dir: Path, icon: Path, tiny: bool = False, cuda: bool = False) -> Path:
    iscc = find_iscc()
    cached = CACHE / "ChineseSimplified.isl"
    se.download(CHINESE_ISL_URL, cached, CHINESE_ISL_SHA256)
    # ISCC only reads .isl files as UTF-8 when they carry a BOM.
    chinese = BUILD / "ChineseSimplified.isl"
    chinese.write_text(cached.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    DIST.mkdir(exist_ok=True)
    flavor = "Tiny-CPU" if tiny else "CUDA" if cuda else "CPU"
    product = f"{APP_NAME} Tiny" if tiny else f"{APP_NAME} CUDA" if cuda else APP_NAME
    app_id = ("{{A920DFB1-485A-4A66-9D91-32116652B412}" if tiny else
              "{{CDA7C9F0-61D2-4F91-A37A-7C4AF8C11902}" if cuda else
              "{{6B2D7F0E-3C1A-4E8B-9F4D-2A7C5E1B8D93}")
    subprocess.run([str(iscc), "/Q", f"/DAppVersion={__version__}", f"/DBuildFlavor={flavor}",
                    f"/DProductName={product}", f"/DProductAppId={app_id}", f"/DSourceDir={app_dir}",
                    f"/DOutputDir={DIST}", f"/DIconFile={icon}", f"/DChineseIsl={chinese}",
                    str(ROOT / "packaging" / "installer.iss")], check=True)
    return DIST / f"{APP_NAME}-{__version__}-{flavor}-Setup.exe"


def package_release(installer: Path) -> Path:
    archive = DIST / (installer.stem.removesuffix("-Setup") + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(installer, installer.name)
        z.write(ROOT / "项目记录.md", "项目记录.md")
        notice = ROOT / "packaging" / "TINY-MODEL-NOTICE.txt"
        if "Tiny-" in installer.name and notice.is_file():
            z.write(notice, notice.name)
        cuda_notice = ROOT / "packaging" / "CUDA-NOTICE.txt"
        if "-CUDA-" in installer.name and cuda_notice.is_file():
            z.write(cuda_notice, cuda_notice.name)
    with zipfile.ZipFile(archive) as z:
        bad = z.testzip()
        if bad is not None:
            raise RuntimeError(f"压缩包校验失败：{bad}")
    return archive


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="构建 Windows CPU、Tiny 或 CUDA 安装包")
    ap.add_argument("--skip-test", action="store_true", help="跳过内置引擎 GTP 自检")
    ap.add_argument("--no-installer", action="store_true", help="只生成 build\\pyi-dist 目录，不编译安装包")
    ap.add_argument("--tiny", action="store_true", help="使用官方10-block小网络，仅打包通用CPU引擎")
    ap.add_argument("--cuda", action="store_true", help="使用官方 CUDA 12.5/cuDNN 9 NVIDIA 引擎，并内置 NVIDIA 运行库")
    a = ap.parse_args(argv)
    if a.tiny and a.cuda:
        ap.error("--tiny 与 --cuda 不能同时使用")

    BUILD.mkdir(exist_ok=True)
    backends = ("eigen",) if a.tiny else ("cuda",) if a.cuda else CPU_BACKENDS
    model_name = se.TINY_MODEL_NAME if a.tiny else se.MODEL_NAME
    assets = fetch_assets(backends, tiny=a.tiny)
    icon = BUILD / "app.ico"
    make_icon(icon)
    app_dir = freeze(icon)
    engine = bundle_engine(app_dir, assets, backends, model_name, tiny=a.tiny, cuda=a.cuda)
    if not a.skip_test:
        smoke(engine, backends, model_name)
    print(f"程序目录：{app_dir}")
    if not a.no_installer:
        installer = compile_installer(app_dir, icon, tiny=a.tiny, cuda=a.cuda)
        print(f"安装包：{installer}")
        print(f"压缩包：{package_release(installer)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
