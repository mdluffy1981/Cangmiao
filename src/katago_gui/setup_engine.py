"""Download and configure KataGo for Cangmiao.

Usage: python -m katago_gui.setup_engine [--backend cuda|opencl|eigenavx2|eigen] [--dest DIR]
       [--model PATH] [--katago PATH] [--config PATH] [--skip-test]
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

from . import paths
from .settings import Settings, SettingsError

KATAGO_VERSION = "v1.18.1"
_REL = f"https://github.com/lightvector/KataGo/releases/download/{KATAGO_VERSION}"
BACKENDS = {
    "cuda": (
        "https://github.com/lightvector/KataGo/releases/download/v1.18.2/"
        "katago-v1.18.2-cuda12.5-cudnn9.8.0-windows-x64.zip",
        "2d88fc26f7a64ae02278240eca87d7c56f149a88674f76b716faf5fc4690f5ac",
        "GPU（NVIDIA CUDA 12.5 + cuDNN 9）",
    ),
    "opencl": (f"{_REL}/katago-{KATAGO_VERSION}-opencl-windows-x64.zip",
               "1710db1903ab921aa6837a9599c8474f8a59f057650217c5d9bc125ee393a9ff",
               "GPU（OpenCL，需要显卡驱动，支持 NVIDIA/AMD/Intel）"),
    "eigenavx2": (f"{_REL}/katago-{KATAGO_VERSION}-eigenavx2-windows-x64.zip",
                  "0d62ffa41ee04dd89dd1b80fe45e306c837231cb1e2dccb4f5780d0ca7c313db",
                  "CPU（需支持 AVX2，速度明显慢于 GPU）"),
    "eigen": (f"{_REL}/katago-{KATAGO_VERSION}-eigen-windows-x64.zip",
              "074485cf150c38aa3bb14ac9f54f2952ffefbceb44673709bbb8a83650bf95d6",
              "CPU（通用，最慢）"),
}
MODEL_NAME = "kata1-b18c384nbt-s9996604416-d4316597426.bin.gz"
MODEL_URL = f"https://media.katagotraining.org/uploaded/networks/models/kata1/{MODEL_NAME}"
MODEL_SHA256 = "9d7a6afed8ff5b74894727e156f04f0cd36060a24824892008fbb6e0cba51f1d"
TINY_MODEL_NAME = "b10c384h6nbttflrs.bin.gz"
TINY_MODEL_URL = f"https://github.com/lightvector/KataGo/releases/download/v1.17.0/{TINY_MODEL_NAME}"
TINY_MODEL_SHA256 = "0ba27eced5180b3e3d0b898b280c541112989765e789d1eb6cd0d31b2b2c1229"

# NVIDIA redistributable DLLs the CUDA KataGo build imports but does not ship (CUDA 12.5 / cuDNN 9.8.0).
_NV = "https://developer.download.nvidia.com/compute"
CUDA_RUNTIME = (
    (f"{_NV}/cuda/redist/libcublas/windows-x86_64/libcublas-windows-x86_64-12.5.3.2-archive.zip",
     "d3628039eb3d39ba9fe6a5350447b10483dd13d5973b5e4cde1d3e917d457d01",
     ("cublas64_*.dll", "cublasLt64_*.dll")),
    (f"{_NV}/cuda/redist/cuda_nvrtc/windows-x86_64/cuda_nvrtc-windows-x86_64-12.5.82-archive.zip",
     "0bc5443fe432d69495412e1ee275fcc5f7590a65bda360ee5e25c20eb192632e",
     ("nvrtc64_*.dll", "nvrtc-builtins64_*.dll")),
    (f"{_NV}/cudnn/redist/cudnn/windows-x86_64/cudnn-windows-x86_64-9.8.0.87_cuda12-archive.zip",
     "d8a23705e3884b137b7e05449fb2b61bfa524e7cfc3fda80743d633f423c6ce4",
     ("cudnn*.dll",)),
)
CUDA_LICENSE_DIR = "NVIDIA-LICENSES"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, expected_sha: str) -> None:
    if dest.is_file() and sha256(dest) == expected_sha:
        print(f"已存在且校验通过：{dest}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    if part.is_file() and sha256(part) == expected_sha:
        part.replace(dest)
        return
    print(f"下载 {url}\n  → {dest}")
    curl = shutil.which("curl.exe") or shutil.which("curl")
    ok = False
    if curl:
        for attempt in range(3):
            r = subprocess.run([curl, "-L", "--fail", "-C", "-", "--connect-timeout", "30",
                                "--max-time", "300", "--retry", "2", "--retry-max-time", "600",
                                "-o", str(part), url])
            if r.returncode == 0:
                ok = True
                break
            print(f"下载失败（curl {r.returncode}），第 {attempt + 1}/3 次尝试", file=sys.stderr)
            if part.is_file() and sha256(part) == expected_sha:
                ok = True
                break
            if r.returncode == 22:
                break
        if not ok:
            raise SystemExit(f"下载失败；已保留 {part}，检查网络后重新运行可继续下载")
    else:
        try:
            with urllib.request.urlopen(url, timeout=60) as resp, part.open("wb") as f:
                shutil.copyfileobj(resp, f, 1 << 20)
        except (OSError, urllib.error.URLError) as e:
            raise SystemExit(f"下载失败：{e}；重新运行可重试") from e
    actual = sha256(part)
    if actual != expected_sha:
        part.unlink(missing_ok=True)
        raise SystemExit(f"校验失败：{dest.name}\n  期望 {expected_sha}\n  实际 {actual}")
    part.replace(dest)


def install_backend(backend: str, dest: Path) -> Path:
    url, sha, _desc = BACKENDS[backend]
    zpath = dest / "downloads" / url.rsplit("/", 1)[1]
    download(url, zpath, sha)
    target = dest / backend
    with zipfile.ZipFile(zpath) as z:
        z.extractall(target)
    exe = next(target.rglob("katago.exe"), None)
    if exe is None:
        raise SystemExit(f"压缩包中没有 katago.exe：{zpath}")
    if backend == "cuda":
        install_cuda_runtime(exe.parent, dest / "downloads")
    return exe


def install_cuda_runtime(target: Path, cache: Path) -> list[Path]:
    """Extract the NVIDIA cuBLAS/NVRTC/cuDNN DLLs and their licenses next to the CUDA katago.exe."""
    installed = []
    for url, sha, patterns in CUDA_RUNTIME:
        archive = cache / url.rsplit("/", 1)[1]
        download(url, archive, sha)
        package = archive.name.removesuffix(".zip")
        matched = set()
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                parts = info.filename.rstrip("/").split("/")
                name = parts[-1]
                if info.is_dir():
                    continue
                pattern = next((p for p in patterns if fnmatch.fnmatch(name.lower(), p.lower())), None)
                if pattern is not None and len(parts) >= 2 and parts[-2].lower() == "bin":
                    matched.add(pattern)
                    dest = target / name
                elif name.upper().startswith("LICENSE") and len(parts) <= 2:
                    dest = target / CUDA_LICENSE_DIR / f"{package}-{name}"
                else:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                installed.append(dest)
        missing = [p for p in patterns if p not in matched]
        if missing:
            raise SystemExit(f"{archive.name} 中缺少运行库：{', '.join(missing)}")
    return installed


def prepare_config(exe: Path, dest: Path) -> Path:
    cfg = dest / "gtp.cfg"
    if cfg.is_file():
        print(f"保留已有配置：{cfg}")
        return cfg
    src = next(exe.parent.rglob("default_gtp.cfg"), None)
    if src is None:
        raise SystemExit("找不到 default_gtp.cfg，请用 --config 指定配置文件")
    shutil.copyfile(src, cfg)
    return cfg


def smoke_test(exe: Path, model: Path, config: Path) -> None:
    print("运行 GTP 自检（首次运行 OpenCL 会对显卡调优，可能需要数分钟）…")
    from .engine.launch import OVERRIDES
    from .engine.gtp import GtpParseError, ResponseAssembler, parse_response
    from .go.coords import from_gtp
    commands = ["protocol_version", "name", "version", "boardsize 9", "clear_board",
                "kata-set-rules chinese", "komi 7.5", "kata-set-param maxVisits 32",
                "kata-set-param maxTime 2", "genmove B", "quit"]
    cmds = "".join(f"{i} {cmd}\n" for i, cmd in enumerate(commands, 1))
    try:
        r = subprocess.run([str(exe), "gtp", "-model", str(model), "-config", str(config), "-override-config", OVERRIDES],
                           input=cmds, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=1800, cwd=str(paths.engine_work_dir()))
    except subprocess.TimeoutExpired:
        raise SystemExit("GTP 自检超时") from None
    try:
        assembler = ResponseAssembler()
        responses = []
        for line in r.stdout.splitlines():
            block = assembler.feed(line)
            if block is not None:
                responses.append(parse_response(block))
        if r.returncode != 0 or [resp.id for resp in responses] != list(range(1, len(commands) + 1)):
            raise ValueError("退出码异常或 GTP 响应不完整")
        if not all(resp.ok for resp in responses) or responses[0].text != "2":
            raise ValueError("GTP 命令失败")
        if not responses[1].text or not responses[2].text:
            raise ValueError("引擎名称或版本为空")
        if responses[-2].text.lower() != "resign":
            from_gtp(responses[-2].text, 9)
    except (GtpParseError, ValueError) as e:
        tail = "\n".join(r.stderr.splitlines()[-15:])
        raise SystemExit(f"GTP 自检失败（退出码 {r.returncode}）：{e}\nstdout:\n{r.stdout}\nstderr 末尾:\n{tail}") from e
    print("GTP 自检通过：" + " / ".join(l for l in r.stdout.splitlines() if l.startswith("=")))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="下载并配置 KataGo 引擎")
    ap.add_argument("--backend", choices=list(BACKENDS), default="opencl",
                    help="引擎构建：opencl（默认，GPU）；NVIDIA CUDA 可选 cuda；CPU 需显式指定 eigenavx2 或 eigen")
    ap.add_argument("--dest", type=Path, default=None, help="安装目录（默认 %%LOCALAPPDATA%%\\KataGoDesktop\\engine）")
    ap.add_argument("--katago", type=Path, help="使用已有的 katago.exe，不下载")
    ap.add_argument("--model", type=Path, help="使用已有的模型文件，不下载")
    ap.add_argument("--config", type=Path, help="使用已有的 GTP 配置文件")
    ap.add_argument("--skip-test", action="store_true", help="跳过 GTP 自检")
    a = ap.parse_args(argv)

    dest = (a.dest or paths.default_engine_dir()).resolve()
    try:
        s = Settings.load()
    except SettingsError as e:
        raise SystemExit(f"{e}\n请先修正设置，原设置文件未修改。") from e
    dest.mkdir(parents=True, exist_ok=True)
    print(f"引擎构建：{a.backend} — {BACKENDS[a.backend][2]}")

    exe = a.katago.resolve() if a.katago else install_backend(a.backend, dest)
    if not exe.is_file():
        raise SystemExit(f"找不到 KataGo：{exe}")
    model = a.model.resolve() if a.model else dest / MODEL_NAME
    if not a.model:
        download(MODEL_URL, model, MODEL_SHA256)
    if not model.is_file():
        raise SystemExit(f"找不到模型：{model}")
    config = a.config.resolve() if a.config else prepare_config(exe, dest)
    if not config.is_file():
        raise SystemExit(f"找不到配置文件：{config}")

    v = subprocess.run([str(exe), "version"], capture_output=True, text=True, timeout=30,
                       encoding="utf-8", errors="replace")
    if v.returncode != 0:
        raise SystemExit(f"katago version 运行失败：{v.stderr or v.stdout}\n"
                         "可能缺少 VC++ 运行库或显卡驱动；CUDA 版需要 NVIDIA 显卡和支持 CUDA 12.5 的驱动。"
                         "GPU 构建失败时可改用 --backend opencl 或 --backend eigenavx2。")
    print(v.stdout.strip())
    if not a.skip_test:
        smoke_test(exe, model, config)

    s.engine.executable, s.engine.model, s.engine.config = str(exe), str(model), str(config)
    s.save()
    print(f"已写入设置：{paths.settings_file()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
