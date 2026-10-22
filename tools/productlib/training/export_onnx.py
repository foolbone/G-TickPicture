#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""快速导出 ONNX（用 legacy exporter，不需要 onnxscript）"""
import sys, os, json
sys.path.insert(0, r'C:\Users\Bone\AppData\Roaming\Python\Python312\site-packages')

import torch
import torch.nn as nn
from torchvision import models
from pathlib import Path

DEVICE = torch.device('cpu')
OUT_DIR = Path(r'D:\G-TickPicture\tools\productlib\models')
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 重建模型
model = models.mobilenet_v2(weights=None)
model.classifier = nn.Sequential(nn.Dropout(0.2), nn.Linear(model.last_channel, 2))

# 加载训练好的权重
pth = Path(r'D:\G-TickPicture\tools\productlib\training\outputs\usage_classifier.pth')
if not pth.exists():
    # 也可能存在 training 目录下
    for cand in Path(r'D:\G-TickPicture\tools\productlib\training').rglob('*.pth'):
        pth = cand
        break

print(f'加载权重: {pth}')
model.load_state_dict(torch.load(pth, map_location=DEVICE))
model.eval()

# 导出 ONNX（legacy exporter）
onnx_path = OUT_DIR / 'usage_cls.onnx'
dummy = torch.randn(1, 3, 224, 224)

# 用 legacy exporter（dynamo=False 避免 onnxscript 依赖）
torch.onnx.export(
    model, dummy, str(onnx_path),
    input_names=['input'], output_names=['logits'],
    dynamic_axes={'input': {0: 'batch'}, 'logits': {0: 'batch'}},
    opset_version=14,
    dynamo=False,  # 关键：用 legacy exporter
)

# 保存 labels
labels = {'classes': ['precheck', 'supervision']}
with open(OUT_DIR / 'usage_labels.json', 'w', encoding='utf-8') as f:
    json.dump(labels, f, ensure_ascii=False, indent=2)

size_mb = onnx_path.stat().st_size / 1024 / 1024
print(f'ONNX 导出完成: {onnx_path} ({size_mb:.1f} MB)')
print(f'Labels: {OUT_DIR / "usage_labels.json"}')
