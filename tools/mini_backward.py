# -*- coding: utf-8 -*-
"""最小 backward 复现：定位是 torch 环境问题还是 GPT-SoVITS 特定模型问题。

覆盖 S2 模型用到的算子类型：Linear(MLP)、Conv、RNN。
运行（在 D:\\Dev\\voiceclone 下）：
  .venv\\Scripts\\python.exe mini_backward.py
结果判断：
  - 全部打印 OK -> torch 基础 backward 正常，问题在 GPT-SoVITS 特定结构
  - 崩在 MLP -> torch/驱动环境问题（换 torch 版本）
  - 崩在 Conv/RNN -> 特定算子 kernel 问题（cuDNN 相关）
"""
import os
os.environ["CUDA_LAUNCH_BLOCKING"] = "1"

import torch
print("torch", torch.__version__, "cuda", torch.version.cuda, "dev", torch.cuda.get_device_name(0))

dev = torch.device("cuda")

# 1) MLP backward
mlp = torch.nn.Sequential(
    torch.nn.Linear(64, 128), torch.nn.ReLU(),
    torch.nn.Linear(128, 64), torch.nn.ReLU(),
    torch.nn.Linear(64, 10),
).to(dev)
opt = torch.optim.Adam(mlp.parameters(), lr=1e-3)
for i in range(20):
    opt.zero_grad()
    x = torch.randn(8, 64, device=dev)
    mlp(x).square().mean().backward()
    opt.step()
print("MLP backward OK")

# 2) Conv1d backward
conv = torch.nn.Conv1d(8, 16, 3, padding=1).to(dev)
opt2 = torch.optim.Adam(conv.parameters(), lr=1e-3)
for i in range(20):
    opt2.zero_grad()
    x = torch.randn(4, 8, 128, device=dev)
    conv(x).square().mean().backward()
    opt2.step()
print("Conv1d backward OK")

# 3) Conv2d backward
conv2 = torch.nn.Conv2d(4, 8, 3, padding=1).to(dev)
opt3 = torch.optim.Adam(conv2.parameters(), lr=1e-3)
for i in range(20):
    opt3.zero_grad()
    x = torch.randn(2, 4, 32, 32, device=dev)
    conv2(x).square().mean().backward()
    opt3.step()
print("Conv2d backward OK")

# 4) LSTM backward（S2 生成器常用）
lstm = torch.nn.LSTM(16, 16, 1, batch_first=True).to(dev)
opt4 = torch.optim.Adam(lstm.parameters(), lr=1e-3)
for i in range(20):
    opt4.zero_grad()
    x = torch.randn(2, 8, 16, device=dev)
    out, _ = lstm(x)
    out.square().mean().backward()
    opt4.step()
print("LSTM backward OK")

print("\n=== 全部 backward 正常：torch 环境 OK ===")
