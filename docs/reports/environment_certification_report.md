# Environment Certification Report

> **Date:** 2026-08-07
> **Purpose:** Pre-Sprint 5A.7 Environment Certification
> **Status:** PARTIAL - Requires Sudo for Full Certification

---

## 1. System Information

| Component | Value | Status |
|-----------|-------|--------|
| OS | Ubuntu 26.04 LTS (Resolute Raccoon) | PASS |
| Kernel | 7.0.0-29-generic | PASS |
| CPU | AMD Ryzen 7 5700X (8 cores, 16 threads) | PASS |
| RAM | 30 GiB (26 GiB available) | PASS |
| Swap | 8 GiB | PASS |
| Disk | 916 GiB NVMe (779 GiB free, 11% used) | PASS |

---

## 2. Toolchain Status

| Tool | Version | Status | Notes |
|------|---------|--------|-------|
| Python | 3.14.4 (system) | PASS | Available at /usr/bin/python3 |
| Python 3.11 | 3.11.15 (uv) | PASS | Installed via uv |
| uv | 0.12.2 | PASS | Available at ~/.local/bin/uv |
| Rust | 1.97.1 | PASS | Installed via rustup |
| Cargo | 1.97.1 | PASS | Installed via rustup |
| git | 2.53.0 | PASS | Available |
| git-lfs | NOT INSTALLED | WARN | Requires: sudo apt install git-lfs |
| cmake | 4.2.3 | PASS | Available |
| gcc | 15.2.0 | PASS | Available |
| g++ | 15.2.0 | PASS | Available |

---

## 3. CUDA/GPU Status

| Component | Value | Status |
|-----------|-------|--------|
| GPU | NVIDIA GeForce RTX 5070 | PASS |
| GPU Memory | 12,227 MiB total (11,123 MiB free) | PASS |
| Compute Cap | 12.0 | PASS |
| NVIDIA Driver | 595.84 | PASS |
| CUDA Version (driver) | 13.2 | PASS |
| CUDA Toolkit (nvcc) | NOT INSTALLED | WARN |
| PyTorch | NOT INSTALLED | WARN |
| cuDNN | NOT INSTALLED | WARN |

Notes:
- NVIDIA driver is installed and functional
- CUDA 13.2 is supported by the driver
- CUDA toolkit (nvcc) not installed - needed for compilation
- PyTorch not installed - needed for model training/evaluation
- SUDO REQUIRED to install: cuda-toolkit-13, Python pip, torch

---

## 4. Docker Status

| Component | Value | Status |
|-----------|-------|--------|
| Docker | 29.1.3 | PASS |
| nvidia-container-toolkit | NOT INSTALLED | WARN |
| GPU Containers | NOT TESTED | WARN |

Notes:
- Docker is installed and running
- nvidia-container-toolkit not installed - GPU containers will not work
- SUDO REQUIRED to install: sudo apt install nvidia-container-toolkit

---

## 5. Atlas Project Status

| Check | Status | Notes |
|-------|--------|-------|
| Project Location | PASS | ~/workspace/atlas-dataset |
| Git Repository | PASS | Branch: atlas-automation-v1.0, clean |
| Python Imports | PASS | atlas_constants, atlas_paths, atlas_schema |
| Build Compilation | PASS | scripts compile without errors |
| Test Suite | PASS | 203/203 tests passing |
| Dataset Access | PASS | curated/, raw/, metadata/ accessible |
| Virtual Environment | PASS | .venv with pytest, jsonschema |

---

## 6. Filesystem Permissions

| Directory | Permissions | Status |
|-----------|-------------|--------|
| ~/workspace/atlas-dataset | drwxrwxr-x (afnan:afnan) | PASS |
| curated/ | drwxrwxr-x | PASS |
| raw/ | drwxrwxr-x | PASS |
| metadata/ | drwxrwxr-x | PASS |
| tests/ | drwxrwxr-x | PASS |
| scripts/ | drwxrwxr-x | PASS |

---

## 7. Environment Variables

| Variable | Value | Status |
|----------|-------|--------|
| PATH | Standard system PATH | WARN |
| CUDA_PATH | Not set | WARN |
| LD_LIBRARY_PATH | Not set | WARN |
| PYTHONPATH | Not set | PASS |
| HF_HOME | Not set | WARN |

PATH Fix Applied:
- Added to ~/.bashrc: export PATH="$PATH:$HOME/.local/bin"
- Added to ~/.bashrc: export PATH="$PATH:$HOME/.cargo/bin"
- Created ~/.bash_profile to source ~/.bashrc for login shells

---

## 8. Issues Requiring Sudo

The following items require sudo access to resolve:

1. git-lfs - sudo apt install git-lfs
2. CUDA Toolkit - sudo apt install cuda-toolkit-13
3. nvidia-container-toolkit - sudo apt install nvidia-container-toolkit
4. PyTorch with CUDA - Install pip then: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu127

---

## 9. Issues Resolved

| Issue | Resolution |
|-------|------------|
| uv not in PATH | Already installed at ~/.local/bin/uv, added to PATH in .bashrc |
| cargo/rustc not in PATH | Already installed at ~/.cargo/bin/, added to PATH in .bashrc |
| .bash_profile missing | Created ~/.bash_profile to source ~/.bashrc |
| Python 3.11 not available | Installed via uv: ~/.local/share/uv/python/cpython-3.11 |
| pytest/jsonschema missing | Created .venv and installed via uv pip |
| Atlas tests failing | All 203 tests now passing |

---

## 10. Recommendations

Immediate (Required for Sprint 5A.7):
1. Install git-lfs - Required for LFS-tracked files
2. Install CUDA Toolkit - Required for PyTorch CUDA builds
3. Install nvidia-container-toolkit - Required for GPU Docker containers
4. Install PyTorch - Required for model training/evaluation

Optional (Recommended):
1. Set HF_HOME environment variable for HuggingFace model cache
2. Configure CUDA_PATH and LD_LIBRARY_PATH after toolkit installation
3. Consider installing clang for C++ extensions

---

## 11. Verification Commands

After sudo fixes, verify:
bash
git-lfs --version
nvcc --version
docker run --rm --gpus all nvidia/cuda:13.2.0-base-ubuntu24.04 nvidia-smi
python3.11 -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"

Atlas verification:
cd ~/workspace/atlas-dataset
.venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/atlas.py --help

---

## 12. Summary

| Category | Status |
|----------|--------|
| OS | PASS |
| CPU/RAM/Disk | PASS |
| Python 3.11 | PASS |
| uv | PASS |
| Rust/Cargo | PASS |
| git | PASS |
| cmake/gcc | PASS |
| Docker | PASS (CPU only) |
| CUDA Driver | PASS |
| CUDA Toolkit | WARN - Requires sudo |
| PyTorch | WARN - Requires sudo |
| git-lfs | WARN - Requires sudo |
| Docker GPU | WARN - Requires sudo |
| Atlas Project | PASS |
| Atlas Tests | PASS - 203/203 passing |

Overall Status: PARTIAL CERTIFICATION
Action Required: Sudo access needed for 4 packages
Blocker: None for non-GPU pipeline work
Ready for: Sprint 5A.7 non-GPU tasks

---

Report generated by Environment Certification Process
Do not proceed to Sprint 5A.7 until sudo issues are resolved
