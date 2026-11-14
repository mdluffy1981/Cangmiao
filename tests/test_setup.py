import subprocess

import pytest

from katago_gui import setup_engine


@pytest.mark.parametrize("code, output", [
    (1, "=1 2\n\n=6 A1\n\n"),
    (0, "=1 2\n\n?4 cannot set boardsize\n\n=6 A1\n\n"),
    (0, "=1 2\n\n=6 NOT_A_MOVE\n\n"),
])
def test_setup_rejects_partial_success(tmp_path, monkeypatch, code, output):
    monkeypatch.setattr(setup_engine.subprocess, "run",
                        lambda *args, **kwargs: subprocess.CompletedProcess(args, code, output, "diagnostic"))
    with pytest.raises(SystemExit, match="自检失败"):
        setup_engine.smoke_test(tmp_path / "katago.exe", tmp_path / "model", tmp_path / "config")


def test_verified_download_cache_is_offline(tmp_path, monkeypatch):
    destination = tmp_path / "archive.zip"
    destination.write_bytes(b"cached")

    def no_network(*args, **kwargs):
        pytest.fail("A verified download must not use the network")

    monkeypatch.setattr(setup_engine.subprocess, "run", no_network)
    monkeypatch.setattr(setup_engine.urllib.request, "urlopen", no_network)
    setup_engine.download("https://example.invalid/download", destination, setup_engine.sha256(destination))


def test_tiny_network_is_pinned_to_official_katago_release():
    assert setup_engine.TINY_MODEL_NAME == "b10c384h6nbttflrs.bin.gz"
    assert setup_engine.TINY_MODEL_URL == (
        "https://github.com/lightvector/KataGo/releases/download/v1.17.0/b10c384h6nbttflrs.bin.gz"
    )
    assert setup_engine.TINY_MODEL_SHA256 == (
        "0ba27eced5180b3e3d0b898b280c541112989765e789d1eb6cd0d31b2b2c1229"
    )


def test_cuda_engine_is_pinned_to_official_windows_release():
    url, digest, description = setup_engine.BACKENDS["cuda"]
    assert url == (
        "https://github.com/lightvector/KataGo/releases/download/v1.18.2/"
        "katago-v1.18.2-cuda12.5-cudnn9.8.0-windows-x64.zip"
    )
    assert digest == "2d88fc26f7a64ae02278240eca87d7c56f149a88674f76b716faf5fc4690f5ac"
    assert "CUDA 12.5" in description and "cuDNN 9" in description


def _fake_redist(path, package, files):
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{package}/LICENSE", "license")
        for name in files:
            z.writestr(f"{package}/{name}", name)


def test_cuda_runtime_extracts_only_bin_dlls_and_licenses(tmp_path, monkeypatch):
    cache, target = tmp_path / "cache", tmp_path / "cuda"
    cache.mkdir()
    layouts = [
        ["bin/cublas64_12.dll", "bin/cublasLt64_12.dll", "bin/nvblas64_12.dll", "lib/x64/cublas.lib"],
        ["bin/nvrtc64_120_0.dll", "bin/nvrtc-builtins64_125.dll"],
        ["bin/cudnn64_9.dll", "bin/cudnn_ops64_9.dll", "include/cudnn.h"],
    ]
    for (url, _sha, _patterns), files in zip(setup_engine.CUDA_RUNTIME, layouts):
        name = url.rsplit("/", 1)[1]
        _fake_redist(cache / name, name.removesuffix(".zip"), files)
    monkeypatch.setattr(setup_engine, "download", lambda url, dest, sha: None)

    setup_engine.install_cuda_runtime(target, cache)

    dlls = sorted(p.name for p in target.glob("*.dll"))
    assert dlls == sorted(["cublas64_12.dll", "cublasLt64_12.dll", "nvrtc64_120_0.dll",
                           "nvrtc-builtins64_125.dll", "cudnn64_9.dll", "cudnn_ops64_9.dll"])
    assert len(list((target / setup_engine.CUDA_LICENSE_DIR).iterdir())) == 3


def test_cuda_runtime_reports_missing_dlls(tmp_path, monkeypatch):
    url = setup_engine.CUDA_RUNTIME[0][0]
    name = url.rsplit("/", 1)[1]
    _fake_redist(tmp_path / name, name.removesuffix(".zip"), ["bin/cublas64_12.dll"])
    monkeypatch.setattr(setup_engine, "download", lambda url, dest, sha: None)
    with pytest.raises(SystemExit, match="cublasLt64"):
        setup_engine.install_cuda_runtime(tmp_path / "cuda", tmp_path)
