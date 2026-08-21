# -*- coding: utf-8 -*-
"""weight_norm 最小复现：确认 GPT-SoVITS 崩溃元凶是否是 weight_norm backward。

运行（D:\\Dev\\voiceclone 下）：
  .venv\\Scripts\\python.exe mini_weightnorm.py
"""
import os
os.environ["CUDA_LAUNCH_BLOCKING"] = "1"

import torch
from torch.nn.utils import weight_norm

# 1) weight_norm Conv1d backward
conv = weight_norm(torch.nn.Conv1d(4, 8, 3, padding=1)).cuda()
opt = torch.optim.Adam(conv.parameters(), lr=1e-3)
for i in range(20):
    opt.zero_grad()
    x = torch.randn(2, 4, 64, device="cuda")
    conv(x).square().mean().backward()
    opt.step()
print("weight_norm Conv1d backward OK")

# 2) weight_norm Conv2d backward
conv2 = weight_norm(torch.nn.Conv2d(4, 8, 3, padding=1)).cuda()
opt2 = torch.optim.Adam(conv2.parameters(), lr=1e-3)
for i in range(20):
    opt2.zero_grad()
    x = torch.randn(2, 4, 16, 16, device="cuda")
    conv2(x).square().mean().backward()
    opt2.step()
print("weight_norm Conv2d backward OK")

print("\n=== weight_norm backward 正常：元凶另有其人 ===")
