#!/usr/bin/env bash
set -euo pipefail
cd /mnt/d/atlas-dataset

echo "PWD: $(pwd)"
echo "BRANCH: $(git branch --show-current)"
echo "STATUS_SHORT:"
git status --short

echo "GPU:"
nvidia-smi --query-gpu=index,name,memory.total,memory.free,driver_version --format=csv,noheader

echo "PYTHON:"
python3 --version
pip3 --version

if [ ! -d ".venv-lora-pilot" ]; then
  python3 -m venv .venv-lora-pilot
fi
source .venv-lora-pilot/bin/activate

pip install --upgrade pip
pip install \
  torch torchvision torchaudio \
  transformers peft bitsandbytes accelerate datasets trl sentencepiece protobuf

python3 -c "import torch; print('CUDA:', torch.cuda.is_available()); print('DEVICE_COUNT:', torch.cuda.device_count()); print('DEVICE_NAME:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else None); print('VRAM_TOTAL:', torch.cuda.get_device_properties(0).total_memory if torch.cuda.is_available() else None)"
python3 -c "import transformers, peft, bitsandbytes, accelerate, datasets, trl; print('transformers', transformers.__version__); print('peft', peft.__version__); print('bitsandbytes', bitsandbytes.__version__); print('accelerate', accelerate.__version__); print('datasets', datasets.__version__); print('trl', trl.__version__)"

python3 scripts/phase2b_materialize.py

sha256sum output/training_views/math_300m_v0.1/train.jsonl output/training_views/math_300m_v0.1/eval.jsonl output/training_views/math_300m_v0.1/manifest.json
