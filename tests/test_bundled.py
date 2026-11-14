from pathlib import Path

import pytest

from katago_gui import bundled
from katago_gui.settings import EngineSettings, Settings


def make_bundle(root: Path, backends=("eigenavx2", "eigen")) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for b in backends:
        (root / b).mkdir()
        (root / b / "katago.exe").write_bytes(b"")
    (root / "model.bin.gz").write_bytes(b"")
    (root / "gtp.cfg").write_text("", encoding="utf-8")
    return root


@pytest.mark.parametrize("avx2, expected", [(True, "eigenavx2"), (False, "eigen")])
def test_bundled_engine_picks_backend_by_cpu(tmp_path, avx2, expected):
    root = make_bundle(tmp_path / "engine")
    es = bundled.bundled_engine(root, avx2)
    assert Path(es.executable) == root / expected / "katago.exe"
    assert Path(es.model) == root / "model.bin.gz" and Path(es.config) == root / "gtp.cfg"
    assert es.missing() == []


def test_bundled_engine_falls_back_to_generic_and_rejects_incomplete(tmp_path):
    root = make_bundle(tmp_path / "engine", backends=("eigen",))
    assert Path(bundled.bundled_engine(root, True).executable).parent.name == "eigen"
    (root / "gtp.cfg").unlink()
    assert bundled.bundled_engine(root, True) is None
    assert bundled.bundled_engine(make_bundle(tmp_path / "e2", backends=("eigenavx2",)), False) is None


def test_tiny_bundle_falls_back_to_its_only_generic_backend(tmp_path):
    root = make_bundle(tmp_path / "tiny", backends=("eigen",))
    (root / "model.bin.gz").rename(root / "b10c384h6nbttflrs.bin.gz")
    engine = bundled.bundled_engine(root, avx2=True)
    assert Path(engine.executable).parent.name == "eigen"
    assert Path(engine.model).name == "b10c384h6nbttflrs.bin.gz"


def test_apply_bundled_engine_fills_missing_settings_and_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("KATAGO_GUI_HOME", str(tmp_path / "home"))
    root = make_bundle(tmp_path / "engine")
    s = Settings()
    assert bundled.apply_bundled_engine(s, root, avx2=True)
    assert Settings.load().engine == s.engine
    assert Path(s.engine.executable).parent.name == "eigenavx2"


def test_apply_bundled_engine_keeps_valid_user_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("KATAGO_GUI_HOME", str(tmp_path / "home"))
    user = make_bundle(tmp_path / "user", backends=("opencl",))
    s = Settings(engine=EngineSettings(str(user / "opencl" / "katago.exe"), str(user / "model.bin.gz"),
                                       str(user / "gtp.cfg")))
    before = s.engine
    assert not bundled.apply_bundled_engine(s, make_bundle(tmp_path / "engine"), avx2=True)
    assert s.engine == before
    assert not (tmp_path / "home" / "settings.json").exists()


def test_apply_bundled_engine_is_noop_from_source(monkeypatch):
    monkeypatch.delattr("sys.frozen", raising=False)
    assert bundled.bundle_root() is None
    assert not bundled.apply_bundled_engine(Settings())


def test_tiny_bundle_uses_isolated_home_and_preserves_override(tmp_path):
    executable = tmp_path / "install" / "Cangmiao.exe"
    engine = executable.parent / "engine"
    engine.mkdir(parents=True)
    (engine / "MODEL-NOTICE.txt").write_text("tiny")
    environ = {"LOCALAPPDATA": str(tmp_path / "local")}

    assert bundled.configure_bundle_home(executable, environ)
    assert environ["KATAGO_GUI_HOME"] == str(tmp_path / "local" / "CangmiaoTiny")

    override = {"KATAGO_GUI_HOME": str(tmp_path / "custom")}
    assert not bundled.configure_bundle_home(executable, override)
    assert override["KATAGO_GUI_HOME"] == str(tmp_path / "custom")


def test_cuda_bundle_selects_cuda_and_uses_isolated_home(tmp_path):
    root = make_bundle(tmp_path / "cuda", backends=("cuda",))
    (root / "CUDA-NOTICE.txt").write_text("CUDA 12.5")
    engine = bundled.bundled_engine(root, avx2=False)
    assert Path(engine.executable) == root / "cuda" / "katago.exe"

    executable = tmp_path / "install" / "Cangmiao.exe"
    install_engine = executable.parent / "engine"
    install_engine.mkdir(parents=True)
    (install_engine / "CUDA-NOTICE.txt").write_text("CUDA 12.5")
    environ = {"LOCALAPPDATA": str(tmp_path / "local")}
    assert bundled.configure_bundle_home(executable, environ)
    assert environ["KATAGO_GUI_HOME"] == str(tmp_path / "local" / "CangmiaoCUDA")


def test_standard_bundle_does_not_change_home(tmp_path):
    executable = tmp_path / "install" / "Cangmiao.exe"
    executable.parent.mkdir()
    environ = {"LOCALAPPDATA": str(tmp_path / "local")}
    assert not bundled.configure_bundle_home(executable, environ)
    assert "KATAGO_GUI_HOME" not in environ
