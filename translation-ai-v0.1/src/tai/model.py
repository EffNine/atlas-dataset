"""Small encoder-decoder Transformer for xx->en translation (from scratch).

Pre-norm Transformer, learned positional embeddings, shared architecture
hyperparams via config dict. No pretrained weights anywhere.
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn


class PositionalEmbedding(nn.Module):
    def __init__(self, vocab: int, d_model: int, max_len: int, pad_id: int, dropout: float):
        super().__init__()
        self.tok = nn.Embedding(vocab, d_model, padding_idx=pad_id)
        self.pos = nn.Embedding(max_len, d_model)
        self.drop = nn.Dropout(dropout)
        self.scale = math.sqrt(d_model)
        self.max_len = max_len

    def forward(self, ids: torch.Tensor) -> torch.Tensor:
        b, t = ids.shape
        if t > self.max_len:
            raise ValueError(f"seq len {t} > max_len {self.max_len}")
        pos = torch.arange(t, device=ids.device).unsqueeze(0).expand(b, t)
        return self.drop(self.tok(ids) * self.scale + self.pos(pos))


class NMTTransformer(nn.Module):
    def __init__(self, cfg: dict):
        super().__init__()
        v, d = cfg["vocab_size"], cfg["d_model"]
        self.pad_id, self.bos_id, self.eos_id = cfg["pad_id"], cfg["bos_id"], cfg["eos_id"]
        self.max_len = cfg["max_len"]
        self.src_emb = PositionalEmbedding(v, d, cfg["max_len"], cfg["pad_id"], cfg["dropout"])
        self.tgt_emb = PositionalEmbedding(v, d, cfg["max_len"], cfg["pad_id"], cfg["dropout"])
        layer = nn.TransformerEncoderLayer(d_model=d, nhead=cfg["n_heads"],
                                           dim_feedforward=cfg["d_ff"],
                                           dropout=cfg["dropout"], batch_first=True,
                                           norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, num_layers=cfg["n_enc_layers"])
        dlayer = nn.TransformerDecoderLayer(d_model=d, nhead=cfg["n_heads"],
                                            dim_feedforward=cfg["d_ff"],
                                            dropout=cfg["dropout"], batch_first=True,
                                            norm_first=True)
        self.decoder = nn.TransformerDecoder(dlayer, num_layers=cfg["n_dec_layers"])
        self.out = nn.Linear(d, v, bias=False)
        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)
            elif isinstance(m, nn.Embedding):
                nn.init.normal_(m.weight, std=0.02)
                with torch.no_grad():
                    m.weight[self.pad_id].zero_()

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())

    def encode(self, src: torch.Tensor, src_key_mask: torch.Tensor) -> torch.Tensor:
        return self.encoder(self.src_emb(src), src_key_padding_mask=src_key_mask)

    def forward(self, src, tgt_in, src_key_mask, tgt_key_mask):
        mem = self.encode(src, src_key_mask)
        t = tgt_in.shape[1]
        causal = nn.Transformer.generate_square_subsequent_mask(t).to(src.device)
        dec = self.decoder(self.tgt_emb(tgt_in), mem, tgt_mask=causal,
                           tgt_key_padding_mask=tgt_key_mask,
                           memory_key_padding_mask=src_key_mask)
        return self.out(dec)

    @torch.no_grad()
    def greedy(self, src: torch.Tensor, src_key_mask: torch.Tensor,
               max_new: int = 128) -> torch.Tensor:
        self.eval()
        mem = self.encode(src, src_key_mask)
        b = src.shape[0]
        out = torch.full((b, 1), self.bos_id, dtype=torch.long, device=src.device)
        for _ in range(max_new):
            t = out.shape[1]
            causal = nn.Transformer.generate_square_subsequent_mask(t).to(src.device)
            dec = self.decoder(self.tgt_emb(out), mem, tgt_mask=causal,
                               memory_key_padding_mask=src_key_mask)
            nxt = self.out(dec[:, -1]).argmax(-1, keepdim=True)
            out = torch.cat([out, nxt], dim=1)
            if (nxt == self.eos_id).all():
                break
        return out
