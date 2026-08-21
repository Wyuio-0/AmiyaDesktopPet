# -*- coding: utf-8 -*-
"""DDP 复现：判别器包在 DistributedDataParallel 里做 backward。

运行（D:\\Dev\\voiceclone 下）：
  .venv\\Scripts\\python.exe mini_ddp.py
"""
import os
os.environ["CUDA_LAUNCH_BLOCKING"] = "1"
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "GPT-SoVITS"))
sys.path.insert(0, os.path.join(HERE, "GPT-SoVITS", "GPT_SoVITS"))
os.chdir(os.path.join(HERE, "GPT-SoVITS"))

import torch
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel

dist.init_process_group(backend="nccl",
                        init_method="tcp://127.0.0.1:29513",
                        world_size=1, rank=0)

from module.models import MultiPeriodDiscriminator  # noqa: E402

net_d = MultiPeriodDiscriminator(use_spectral_norm=False, version="v2").cuda()
net_d = DistributedDataParallel(net_d, device_ids=[0],
                                find_unused_parameters=True)
opt = torch.optim.AdamW(net_d.parameters(), lr=1e-4)
y = torch.randn(2, 1, 32000, device="cuda")
for i in range(5):
    opt.zero_grad()
    y_d_hat_r, y_d_hat_g, _, _ = net_d(y, y)
    loss = sum(torch.mean(v) for v in y_d_hat_r) + \
           sum(torch.mean(v) for v in y_d_hat_g)
    loss.backward()
    opt.step()
    print("iter %d loss=%.4f" % (i, float(loss)), flush=True)
dist.destroy_process_group()
print("\n=== DDP 判别器 backward OK：DDP 不是元凶 ===")
