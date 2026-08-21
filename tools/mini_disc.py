# -*- coding: utf-8 -*-
"""判别器复现：完整 MultiPeriodDiscriminator + 非方形 Conv2d + 分组 Conv1d。

运行（D:\\Dev\\voiceclone 下）：
  .venv\\Scripts\\python.exe mini_disc.py
"""
import os
os.environ["CUDA_LAUNCH_BLOCKING"] = "1"
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "GPT-SoVITS"))
sys.path.insert(0, os.path.join(HERE, "GPT-SoVITS", "GPT_SoVITS"))
os.chdir(os.path.join(HERE, "GPT-SoVITS"))

import torch

dev = torch.device("cuda")

# 1) 非方形 Conv2d：kernel (5,1) stride (3,1)（DiscriminatorP 风格）
conv_p = torch.nn.Conv2d(1, 32, (5, 1), (3, 1), padding=(2, 0)).to(dev)
opt1 = torch.optim.Adam(conv_p.parameters(), lr=1e-3)
for i in range(10):
    opt1.zero_grad()
    x = torch.randn(2, 1, 8, 64, device=dev)   # (b,c,t//period,period)
    conv_p(x).square().mean().backward()
    opt1.step()
print("non-square Conv2d (k=5,1 s=3,1) backward OK")

# 2) 分组 Conv1d：groups=16（DiscriminatorS 风格）
conv_g = torch.nn.Conv1d(64, 256, 41, 4, groups=16, padding=20).to(dev)
opt2 = torch.optim.Adam(conv_g.parameters(), lr=1e-3)
for i in range(10):
    opt2.zero_grad()
    x = torch.randn(2, 64, 256, device=dev)
    conv_g(x).square().mean().backward()
    opt2.step()
print("grouped Conv1d (groups=16) backward OK")

# 3) 完整判别器：MultiPeriodDiscriminator（use_spectral_norm=False, v2）
from module.models import MultiPeriodDiscriminator  # noqa: E402
net_d = MultiPeriodDiscriminator(use_spectral_norm=False, version="v2").to(dev)
opt3 = torch.optim.AdamW(net_d.parameters(), lr=1e-4)
y = torch.randn(2, 1, 32000, device=dev)
for i in range(5):
    opt3.zero_grad()
    y_d_hat_r, y_d_hat_g, _, _ = net_d(y, y)
    loss = sum(torch.mean(v) for v in y_d_hat_r) + \
           sum(torch.mean(v) for v in y_d_hat_g)
    loss.backward()
    opt3.step()
print("MultiPeriodDiscriminator backward OK")

print("\n=== 判别器全部正常：崩在别处 ===")
