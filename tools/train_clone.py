# -*- coding: utf-8 -*-
"""GPT-SoVITS S2 一键微调脚本（通用，任意角色）。

放到 D:\\Dev\\voiceclone 后运行。提供语音 + 文本标注即可，脚本自动完成：
  预处理(1a get-text / 1b get-hubert / 1c get-semantic) → S2 单进程训练 → G_*.pth

两种输入方式（二选一）：
  方式 A：直接给 GPT-SoVITS 的 list 文件
    .venv\\Scripts\\python.exe train_clone.py --name mychar --list mychar.list
    list 每行： <音频绝对路径>|<角色名>|zh|<该条语音文本>

  方式 B：给音频目录 + 文本映射 JSON（推荐，更省事）
    .venv\\Scripts\\python.exe train_clone.py --name mychar --audio-dir D:/voice --texts texts.json
    texts.json 形如 {"文件名不含扩展名": "文本", ...}

双击运行：直接双击 train_clone.bat，按提示输入。

关键参数：
  --epochs 20  训练轮数（默认 20）
  --batch 2    批大小（默认 2）
  --fp16       用 fp16（默认纯 FP32；崩溃时可选）
  --skip-preprocess  已做过预处理可跳过

内置 RTX 5060（Blackwell）兼容：单进程 + 假 DDP + 关 GradScaler + num_workers=0
（详见仓库 train_angelina_clone.py 的排查记录）。

训练产物：<name>_model\\logs_s2_v2\\G_*.pth
完成后：把 serve.py 该角色的 tuned_s2_dir 指向 <name>_model\\logs_s2_v2
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GSV = os.path.join(HERE, "GPT-SoVITS")
PY = os.path.join(HERE, ".venv", "Scripts", "python.exe")
FFMPEG_DIR = os.path.join(HERE, ".venv", "Lib", "site-packages",
                          "imageio_ffmpeg", "binaries")

PRE = os.path.join("GPT_SoVITS", "pretrained_models")
BERT_DIR = os.path.join(PRE, "chinese-roberta-wwm-ext-large")
HUBERT_DIR = os.path.join(PRE, "chinese-hubert-base")
V2FINAL = os.path.join(PRE, "gsv-v2final-pretrained")
S2G = os.path.join(GSV, V2FINAL, "s2G2333k.pth")
S2D = os.path.join(GSV, V2FINAL, "s2D2333k.pth")
VERSION = "v2"


# ── 输入：生成/校验 list ─────────────────────────────────────────

def build_list_from_texts(name, audio_dir, texts):
    """根据音频目录 + 文本映射 JSON 生成 GPT-SoVITS list 内容。"""
    with open(texts, encoding="utf-8") as f:
        mapping = json.load(f)
    if not isinstance(mapping, dict):
        sys.exit("--texts 文件必须是 JSON 对象：{文件名: 文本}")

    lines = []
    skipped = []
    for fn in sorted(os.listdir(audio_dir)):
        if not fn.lower().endswith((".wav", ".mp3", ".flac", ".ogg")):
            continue
        stem = os.path.splitext(fn)[0]
        text = mapping.get(stem) or mapping.get(fn)
        if not text:
            skipped.append(fn)
            continue
        path = os.path.join(audio_dir, fn).replace("\\", "/")
        lines.append("%s|%s|zh|%s" % (path, name, str(text).strip()))
    if skipped:
        print("警告：以下音频无文本标注，已跳过：%s" % skipped, flush=True)
    if not lines:
        sys.exit("没有生成任何训练条目，请检查 --audio-dir 与 --texts。")
    return "\n".join(lines) + "\n"


def ensure_list(name, list_file, audio_dir, texts):
    """返回 list 文件路径：优先用现成 list，否则由 texts 生成。"""
    if list_file:
        if not os.path.isfile(list_file):
            sys.exit("找不到 list 文件：%s" % list_file)
        return list_file
    content = build_list_from_texts(name, audio_dir, texts)
    path = os.path.join(HERE, "%s.list" % name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("已生成 list：%s（%d 条）" % (path, content.count("\n")), flush=True)
    return path


# ── 预处理（1a/1b/1c）────────────────────────────────────────────

def _run_script(script, env_extra, label):
    env = os.environ.copy()
    env.update({k: str(v) for k, v in env_extra.items()})
    env["is_half"] = "False"
    env["i_part"] = "0"
    env["all_parts"] = "1"
    env["_CUDA_VISIBLE_DEVICES"] = "0"
    env["version"] = VERSION
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [GSV, os.path.join(GSV, "GPT_SoVITS"), env.get("PYTHONPATH", "")])
    env["PATH"] = os.pathsep.join([FFMPEG_DIR, env.get("PATH", "")])
    print("\n=== %s ===" % label, flush=True)
    p = subprocess.run([PY, "-s", script], cwd=GSV, env=env)
    if p.returncode != 0:
        sys.exit("%s 失败（exit %d）" % (label, p.returncode))


def _merge_parts(opt_dir, pattern, out_path, header=None):
    part = os.path.join(opt_dir, pattern % 0)
    if not os.path.isfile(part):
        if os.path.isfile(out_path):
            return
        sys.exit("缺少中间文件：%s" % part)
    rows = [header] if header else []
    with open(part, encoding="utf-8") as f:
        rows += f.read().strip("\n").split("\n")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    os.remove(part)


def preprocess(name, inp_list, opt_dir):
    os.makedirs(opt_dir, exist_ok=True)
    common = {"inp_text": inp_list, "inp_wav_dir": "",
              "exp_name": name, "opt_dir": opt_dir}

    path_text = os.path.join(opt_dir, "2-name2text.txt")
    if not os.path.isfile(path_text):
        _run_script(os.path.join("GPT_SoVITS", "prepare_datasets", "1-get-text.py"),
                    dict(common, bert_pretrained_dir=BERT_DIR), "1a get-text")
        _merge_parts(opt_dir, "2-name2text-%d.txt", path_text)
    else:
        print("1a get-text 已完成", flush=True)

    hubert_dir = os.path.join(opt_dir, "4-cnhubert")
    if not os.path.isdir(hubert_dir) or not os.listdir(hubert_dir):
        _run_script(os.path.join("GPT_SoVITS", "prepare_datasets",
                                 "2-get-hubert-wav32k.py"),
                    dict(common, cnhubert_base_dir=HUBERT_DIR),
                    "1b get-hubert-wav32k")
    else:
        print("1b get-hubert 已完成", flush=True)

    path_semantic = os.path.join(opt_dir, "6-name2semantic.tsv")
    if not os.path.isfile(path_semantic):
        _run_script(os.path.join("GPT_SoVITS", "prepare_datasets", "3-get-semantic.py"),
                    dict(common, pretrained_s2G=S2G,
                         s2config_path=os.path.join("GPT_SoVITS", "configs", "s2.json")),
                    "1c get-semantic")
        _merge_parts(opt_dir, "6-name2semantic-%d.tsv", path_semantic,
                     header="item_name\tsemantic_audio")
    else:
        print("1c get-semantic 已完成", flush=True)


# ── 训练（单进程 + RTX 5060 兼容）────────────────────────────────

def write_s2_config(name, opt_dir, epochs, batch, fp16):
    with open(os.path.join(GSV, "GPT_SoVITS", "configs", "s2.json"),
              encoding="utf-8") as f:
        data = json.load(f)
    d = data["train"]
    d["fp16_run"] = fp16
    d["batch_size"] = batch
    d["epochs"] = epochs
    d["text_low_lr_rate"] = 0.4
    d["pretrained_s2G"] = S2G
    d["pretrained_s2D"] = S2D
    d["if_save_latest"] = 0
    d["if_save_every_weights"] = True
    d["save_every_epoch"] = 2
    d["gpu_numbers"] = "0"
    d["grad_ckpt"] = False
    data["model"]["version"] = VERSION
    data["data"]["exp_dir"] = opt_dir
    data["s2_ckpt_dir"] = os.path.join(opt_dir, "logs_s2_%s" % VERSION)
    data["save_weight_dir"] = os.path.join(opt_dir, "logs_s2_%s" % VERSION, "weights")
    data["name"] = name
    data["version"] = VERSION
    os.makedirs(os.path.join(opt_dir, "logs_s2_%s" % VERSION), exist_ok=True)
    os.makedirs(data["save_weight_dir"], exist_ok=True)
    cfg_path = os.path.join(opt_dir, "s2_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return cfg_path


def train(name, opt_dir, epochs, batch, fp16, no_cudnn, tf32):
    cfg_path = write_s2_config(name, opt_dir, epochs, batch, fp16)

    os.environ["CUDA_LAUNCH_BLOCKING"] = "1"
    os.environ["MASTER_ADDR"] = "localhost"
    os.environ["MASTER_PORT"] = "29513"
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    os.environ["PATH"] = os.pathsep.join([FFMPEG_DIR, os.environ.get("PATH", "")])

    sys.path.insert(0, GSV)
    sys.path.insert(0, os.path.join(GSV, "GPT_SoVITS"))
    os.chdir(GSV)
    sys.argv = ["s2_train.py", "--config", cfg_path]

    import faulthandler
    faulthandler.enable()

    import torch
    if no_cudnn:
        torch.backends.cudnn.enabled = False
    if tf32:
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.set_float32_matmul_precision("medium")
    else:
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.set_float32_matmul_precision("highest")

    # 关 GradScaler（Blackwell 上 fp16 自动缩放 backward 段错误）
    import torch.cuda.amp as _amp
    _orig_scaler = _amp.GradScaler

    def _no_scaler(*aa, **kw):
        kw["enabled"] = False
        return _orig_scaler(*aa, **kw)

    _amp.GradScaler = _no_scaler

    # 假 DDP：单进程训练（Windows torch 无 NCCL，DDP backward 原生崩溃）
    class _NoDDP:
        def __new__(cls, module, *aa, **kw):
            object.__setattr__(module, "module", module)
            return module

    import torch.nn.parallel as _np
    _np.DistributedDataParallel = _NoDDP

    # DataLoader 单进程
    import torch.utils.data as _tud
    _orig_dl = _tud.DataLoader

    def _patched_dl(*aa, **kw):
        kw["num_workers"] = 0
        kw["persistent_workers"] = False
        kw.pop("prefetch_factor", None)
        return _orig_dl(*aa, **kw)

    _tud.DataLoader = _patched_dl

    import GPT_SoVITS.s2_train as s2
    s2.DataLoader = _patched_dl

    print("torch %s cuda %s fp16=%s batch=%d epochs=%d" %
          (torch.__version__, torch.version.cuda, fp16, batch, epochs), flush=True)
    s2.run(0, 1, s2.hps)

    ckpt_dir = os.path.join(opt_dir, "logs_s2_%s" % VERSION)
    ckpts = sorted(f for f in os.listdir(ckpt_dir) if f.startswith("G_"))
    print("\n=== 训练完成 ===", flush=True)
    print("检查点：%s" % ckpts, flush=True)
    print("serve.py 配置：把该角色的 tuned_s2_dir 指向 %s" % ckpt_dir, flush=True)


def main():
    ap = argparse.ArgumentParser(description="GPT-SoVITS S2 一键微调")
    ap.add_argument("--name", required=True, help="角色 key，如 amiya2")
    ap.add_argument("--list", default="", help="GPT-SoVITS list 文件（音频路径|name|zh|文本）")
    ap.add_argument("--audio-dir", default="", help="音频目录（配合 --texts 使用）")
    ap.add_argument("--texts", default="", help="文本映射 JSON：{文件名: 文本}")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--fp16", action="store_true")
    ap.add_argument("--tf32", action="store_true")
    ap.add_argument("--no-cudnn", action="store_true")
    ap.add_argument("--skip-preprocess", action="store_true")
    a = ap.parse_args()

    name = a.name.strip()
    if not name:
        sys.exit("--name 不能为空")
    if not a.list and not (a.audio_dir and a.texts):
        sys.exit("请提供 --list，或同时提供 --audio-dir 与 --texts")

    opt_dir = os.path.join(HERE, "%s_model" % name)
    inp_list = ensure_list(name, a.list or "", a.audio_dir, a.texts)

    if not a.skip_preprocess:
        preprocess(name, inp_list, opt_dir)
    else:
        print("跳过预处理（--skip-preprocess）", flush=True)

    train(name, opt_dir, a.epochs, a.batch, a.fp16, a.no_cudnn, a.tf32)


if __name__ == "__main__":
    main()
