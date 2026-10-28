"""Unit tests: model forward + greedy decode shapes (CPU, tiny)."""
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tai.model import NMTTransformer  # noqa: E402

CFG = {"vocab_size": 64, "d_model": 32, "n_heads": 4, "d_ff": 64,
       "n_enc_layers": 1, "n_dec_layers": 1, "dropout": 0.0,
       "max_len": 16, "pad_id": 0, "bos_id": 1, "eos_id": 2}


def test_forward_shape():
    m = NMTTransformer(CFG)
    src = torch.randint(3, 64, (2, 7))
    tgt = torch.randint(3, 64, (2, 5))
    logits = m(src, tgt, src == 0, tgt == 0)
    assert logits.shape == (2, 5, 64)
    assert torch.isfinite(logits).all()


def test_greedy_terminates():
    m = NMTTransformer(CFG)
    src = torch.randint(3, 64, (2, 7))
    out = m.greedy(src, src == 0, max_new=10)
    assert out.shape[0] == 2 and out.shape[1] <= 11
    assert (out[:, 0] == 1).all()  # starts with BOS


def test_param_count_small():
    assert NMTTransformer(CFG).n_params() < 200_000
