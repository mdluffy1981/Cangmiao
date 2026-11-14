import runpy
import zipfile
from pathlib import Path

import pytest

from katago_gui import APP_NAME, __version__
from katago_gui import setup_engine


def test_cpu_release_archive(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    build = runpy.run_path(str(root / "packaging" / "build_installer.py"))
    package = build["package_release"]
    monkeypatch.setitem(package.__globals__, "ROOT", tmp_path)
    monkeypatch.setitem(package.__globals__, "DIST", tmp_path)
    installer = tmp_path / f"{APP_NAME}-{__version__}-CPU-Setup.exe"
    installer.write_bytes(b"installer-test")
    record = tmp_path / "项目记录.md"
    record.write_text("release-test", encoding="utf-8")
    archive = package(installer)
    assert archive.name == f"{APP_NAME}-{__version__}-CPU.zip"
    with zipfile.ZipFile(archive) as z:
        assert z.namelist() == [installer.name, record.name]
        assert z.read(installer.name) == installer.read_bytes()
        assert z.read(record.name) == record.read_bytes()
        assert z.testzip() is None


def test_tiny_release_archive_includes_model_notice(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    build = runpy.run_path(str(root / "packaging" / "build_installer.py"))
    package = build["package_release"]
    monkeypatch.setitem(package.__globals__, "ROOT", root)
    monkeypatch.setitem(package.__globals__, "DIST", tmp_path)
    installer = tmp_path / f"Cangmiao-{__version__}-Tiny-CPU-Setup.exe"
    installer.write_bytes(b"tiny-installer")
    archive = package(installer)
    assert archive.name == f"Cangmiao-{__version__}-Tiny-CPU.zip"
    with zipfile.ZipFile(archive) as z:
        assert z.namelist() == [installer.name, "项目记录.md", "TINY-MODEL-NOTICE.txt"]
        assert b"10 blocks" in z.read("TINY-MODEL-NOTICE.txt")
        assert z.testzip() is None


def test_cuda_release_archive_includes_cuda_notice(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    build = runpy.run_path(str(root / "packaging" / "build_installer.py"))
    package = build["package_release"]
    monkeypatch.setitem(package.__globals__, "ROOT", root)
    monkeypatch.setitem(package.__globals__, "DIST", tmp_path)
    installer = tmp_path / f"Cangmiao-{__version__}-CUDA-Setup.exe"
    installer.write_bytes(b"cuda-installer")
    archive = package(installer)
    assert archive.name == f"Cangmiao-{__version__}-CUDA.zip"
    with zipfile.ZipFile(archive) as z:
        assert z.namelist() == [installer.name, "项目记录.md", "CUDA-NOTICE.txt"]
        notice = z.read("CUDA-NOTICE.txt")
        assert b"CUDA 12.5" in notice and b"cuDNN 9" in notice
        assert z.testzip() is None


def test_tiny_asset_selection_and_engine_bundle(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    build = runpy.run_path(str(root / "packaging" / "build_installer.py"))
    calls = []

    def fake_download(url, destination, expected_sha):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"verified test asset")
        calls.append((url, destination.name, expected_sha))

    monkeypatch.setitem(build["fetch_assets"].__globals__, "CACHE", tmp_path / "cache")
    monkeypatch.setitem(build["se"].__dict__, "download", fake_download)
    assets = build["fetch_assets"](backends=("eigen",), tiny=True)
    assert set(assets) == {"eigen", "model"}
    assert calls == [
        (setup_engine.BACKENDS["eigen"][0],
         setup_engine.BACKENDS["eigen"][0].rsplit("/", 1)[1],
         setup_engine.BACKENDS["eigen"][1]),
        (setup_engine.TINY_MODEL_URL, setup_engine.TINY_MODEL_NAME, setup_engine.TINY_MODEL_SHA256),
    ]

    source = tmp_path / "engine.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("katago.exe", b"engine")
        archive.writestr("default_gtp.cfg", "config")
    assets["eigen"] = source
    assets["model"] = tmp_path / setup_engine.TINY_MODEL_NAME
    assets["model"].write_bytes(b"model")
    app_dir = tmp_path / "app"
    engine = build["bundle_engine"](app_dir, assets, ("eigen",), setup_engine.TINY_MODEL_NAME, tiny=True)
    assert (engine / "eigen" / "katago.exe").is_file()
    assert not (engine / "eigenavx2").exists()
    assert (engine / setup_engine.TINY_MODEL_NAME).read_bytes() == b"model"
    assert (engine / "MODEL-NOTICE.txt").is_file()
    assert (engine / "gtp.cfg").read_text(encoding="utf-8") == "config"


def test_cuda_asset_selection_and_engine_bundle(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    build = runpy.run_path(str(root / "packaging" / "build_installer.py"))
    calls = []

    def fake_download(url, destination, expected_sha):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"verified test asset")
        calls.append((url, destination.name, expected_sha))

    monkeypatch.setitem(build["fetch_assets"].__globals__, "CACHE", tmp_path / "cache")
    monkeypatch.setitem(build["se"].__dict__, "download", fake_download)
    assets = build["fetch_assets"](backends=("cuda",))
    assert set(assets) == {"cuda", "model"}
    assert calls == [
        (setup_engine.BACKENDS["cuda"][0],
         setup_engine.BACKENDS["cuda"][0].rsplit("/", 1)[1],
         setup_engine.BACKENDS["cuda"][1]),
        (setup_engine.MODEL_URL, setup_engine.MODEL_NAME, setup_engine.MODEL_SHA256),
    ]

    source = tmp_path / "cuda.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("katago.exe", b"engine")
        archive.writestr("cudnn64_9.dll", b"runtime")
        archive.writestr("default_gtp.cfg", "config")
    assets["cuda"] = source
    runtime_calls = []
    monkeypatch.setitem(build["se"].__dict__, "install_cuda_runtime",
                        lambda target, cache: runtime_calls.append((target, cache)))
    app_dir = tmp_path / "app"
    engine = build["bundle_engine"](app_dir, assets, ("cuda",), cuda=True)
    assert runtime_calls == [(engine / "cuda", tmp_path / "cache")]
    assert (engine / "cuda" / "katago.exe").is_file()
    assert (engine / "cuda" / "cudnn64_9.dll").read_bytes() == b"runtime"
    assert (engine / "CUDA-NOTICE.txt").is_file()
    assert (engine / "gtp.cfg").read_text(encoding="utf-8") == "config"


def test_packaging_rejects_combining_tiny_and_cuda_modes(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    build = runpy.run_path(str(root / "packaging" / "build_installer.py"))
    monkeypatch.setitem(build, "BUILD", tmp_path / "build")
    with pytest.raises(SystemExit) as exc:
        build["main"](["--tiny", "--cuda"])
    assert exc.value.code == 2
    assert not (tmp_path / "build").exists()
