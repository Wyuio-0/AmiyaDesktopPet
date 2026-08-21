# -*- coding: utf-8 -*-
"""予愿安洁莉娜 S2 微调 —— 单进程完整训练版。

为什么有这个文件：s2_train.py 默认用 torch.multiprocessing.spawn + DataLoader
多进程（num_workers=5），在 RTX 5060（Blackwell, sm_120）的 Windows 环境里
CUDA 段错误（0xC0000005 / access violation）。serve.py 已验证：单线程 +
CUDA_LAUNCH_BLOCKING=1 才能稳定。本脚本照此规避：

  1. 不经过 mp.spawn，直接在当前进程调用 s2.run(...)
  2. DataLoader 强制 num_workers=0
  3. CUDA_LAUNCH_BLOCKING=1（同步 CUDA 启动，错误即时报出）
  4. batch_size 默认 2（38 条数据足够小）；--fp16 可选（不同 CUDA kernel，
     若 fp16 off 崩溃可尝试开启）

用法：把本文件放到 D:\\Dev\\voiceclone 后运行
  .venv\\Scripts\\python.exe train_angelina_clone.py [--epochs 20] [--batch 2] [--fp16]

训练产物：yuyuananjielina_model\\logs_s2_v2\\G_*.pth
（预处理 1a/1b/1c 已完成，本脚本直接训练。）
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GSV = os.path.join(HERE, "GPT-SoVITS")
sys.path.insert(0, GSV)
sys.path.insert(0, os.path.join(GSV, "GPT_SoVITS"))
os.chdir(GSV)

# ── RTX 5060 稳定手段（serve.py 同款）────────────────────────────
os.environ["CUDA_LAUNCH_BLOCKING"] = "1"
os.environ["MASTER_ADDR"] = "localhost"
os.environ["MASTER_PORT"] = "29513"
os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"

FFMPEG_DIR = os.path.join(HERE, ".venv", "Lib", "site-packages",
                          "imageio_ffmpeg", "binaries")
os.environ["PATH"] = os.pathsep.join([FFMPEG_DIR, os.environ.get("PATH", "")])

import faulthandler  # noqa: E402
faulthandler.enable()

ap = argparse.ArgumentParser()
ap.add_argument("--epochs", type=int, default=20)
ap.add_argument("--batch", type=int, default=2)
ap.add_argument("--fp16", action="store_true")
a = ap.parse_args()

# ── 写训练配置（s2_train import 时读取）────────────────────────────
CFG = os.path.join(HERE, "yuyuananjielina_model", "s2_config.json")
with open(CFG, encoding="utf-8") as f:
    data = json.load(f)
data["train"]["epochs"] = a.epochs
data["train"]["batch_size"] = a.batch
data["train"]["fp16_run"] = a.fp16
with open(CFG, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

sys.argv = ["s2_train.py", "--config", CFG]

import torch  # noqa: E402
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True
torch.set_float32_matmul_precision("medium")
print("torch %s  cuda %s  fp16=%s batch=%d epochs=%d"
      % (torch.__version__, torch.version.cuda, a.fp16, a.batch, a.epochs),
      flush=True)

# ── 强制 DataLoader 单进程（s2_train 硬编码 num_workers=5）──────────
import torch.utils.data as _tud  # noqa: E402
_orig_dl = _tud.DataLoader


def _patched_dl(*aa, **kw):
    kw["num_workers"] = 0
    kw["persistent_workers"] = False
    kw.pop("prefetch_factor", None)
    return _orig_dl(*aa, **kw)


_tud.DataLoader = _patched_dl

import GPT_SoVITS.s2_train as s2  # noqa: E402
s2.DataLoader = _patched_dl

print("== 开始单进程训练（epochs=%d batch=%d fp16=%s）=="
      % (a.epochs, a.batch, a.fp16), flush=True)
s2.run(0, 1, s2.hps)
print("\n=== 训练完成 ===", flush=True)
ckpt = os.path.join(HERE, "yuyuananjielina_model", "logs_s2_v2")
print("检查点目录：%s" % ckpt, flush=True)
print("权重：%s" % sorted(f for f in os.listdir(ckpt) if f.startswith("G_")),
      flush=True)
