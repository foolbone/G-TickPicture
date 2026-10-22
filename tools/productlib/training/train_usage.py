#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
train_usage.py — 训练监装/预检二分类器，导出 ONNX

数据: dataset_usage/train/{precheck,supervision}
输出: models/usage_cls.onnx + models/usage_labels.json
"""
import os, sys, json, time
from pathlib import Path

# PyTorch 在 user site-packages
sys.path.insert(0, r'C:\Users\Bone\AppData\Roaming\Python\Python312\site-packages')

from PIL import Image, ImageFile
Image.MAX_IMAGE_PIXELS = None
ImageFile.LOAD_TRUNCATED_IMAGES = True

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torchvision import datasets, models, transforms

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
DATA_ROOT = Path(__file__).parent / 'dataset_usage'
OUT_DIR = Path(__file__).parent.parent / 'models'
CLASSES = ['precheck', 'supervision']


def make_transforms(train=True):
    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                    std=[0.229, 0.224, 0.225])
    if train:
        return transforms.Compose([
            transforms.Resize((256, 256)),
            transforms.RandomCrop(224),
            transforms.RandomHorizontalFlip(),
            transforms.ColorJitter(brightness=0.2, contrast=0.2),
            transforms.RandomRotation(15),
            transforms.ToTensor(), normalize,
        ])
    return transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(), normalize,
    ])


def main():
    print(f'设备: {DEVICE}')
    print(f'数据: {DATA_ROOT}')

    train_ds = datasets.ImageFolder(str(DATA_ROOT / 'train'), transform=make_transforms(True))
    val_ds = datasets.ImageFolder(str(DATA_ROOT / 'val'), transform=make_transforms(False))
    print(f'训练集: {len(train_ds)} 张, 类别: {train_ds.classes}')
    print(f'验证集: {len(val_ds)} 张, 类别: {val_ds.classes}')

    # 类别加权（precheck 640 vs supervision 217）
    counts = [0] * len(CLASSES)
    for _, idx in train_ds.samples:
        counts[idx] += 1
    weights = torch.tensor([1.0 / max(c, 1) for c in counts], dtype=torch.float32)
    weights = weights / weights.sum() * len(CLASSES)
    print(f'类别样本: {counts}, 权重: {[f"{w:.2f}" for w in weights]}')

    train_loader = DataLoader(train_ds, batch_size=32, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=64, shuffle=False, num_workers=0)

    model = models.mobilenet_v2(weights=models.MobileNet_V2_Weights.IMAGENET1K_V2)
    model.classifier = nn.Sequential(nn.Dropout(0.2), nn.Linear(model.last_channel, 2))
    model = model.to(DEVICE)
    criterion = nn.CrossEntropyLoss(weight=weights.to(DEVICE))

    # Stage 1: 冻结骨干
    print('\n--- Stage 1: 冻结骨干，训练分类头 (5 epoch) ---')
    for p in model.features.parameters():
        p.requires_grad = False
    optimizer = optim.AdamW(model.classifier.parameters(), lr=1e-3, weight_decay=1e-4)
    for epoch in range(5):
        model.train()
        tl, ta = 0, 0
        for imgs, lbls in train_loader:
            imgs, lbls = imgs.to(DEVICE), lbls.to(DEVICE)
            optimizer.zero_grad()
            out = model(imgs)
            loss = criterion(out, lbls)
            loss.backward()
            optimizer.step()
            tl += loss.item() * imgs.size(0)
            ta += (out.argmax(1) == lbls).sum().item()
        # eval
        model.eval()
        vl, va = 0, 0
        with torch.no_grad():
            for imgs, lbls in val_loader:
                imgs, lbls = imgs.to(DEVICE), lbls.to(DEVICE)
                out = model(imgs)
                vl += criterion(out, lbls).item() * imgs.size(0)
                va += (out.argmax(1) == lbls).sum().item()
        print(f'  E{epoch+1}: train_acc={ta/len(train_ds):.3f} val_acc={va/len(val_ds):.3f}')

    # Stage 2: 解冻微调
    print('\n--- Stage 2: 解冻最后20层微调 (8 epoch) ---')
    for p in model.features[-20:].parameters():
        p.requires_grad = True
    optimizer = optim.AdamW([
        {'params': model.features[-20:].parameters(), 'lr': 1e-5},
        {'params': model.classifier.parameters(), 'lr': 1e-4},
    ], weight_decay=1e-4)

    best_acc = 0
    best_state = None
    for epoch in range(8):
        model.train()
        tl, ta = 0, 0
        for imgs, lbls in train_loader:
            imgs, lbls = imgs.to(DEVICE), lbls.to(DEVICE)
            optimizer.zero_grad()
            out = model(imgs)
            loss = criterion(out, lbls)
            loss.backward()
            optimizer.step()
            tl += loss.item() * imgs.size(0)
            ta += (out.argmax(1) == lbls).sum().item()
        model.eval()
        vl, va = 0, 0
        with torch.no_grad():
            for imgs, lbls in val_loader:
                imgs, lbls = imgs.to(DEVICE), lbls.to(DEVICE)
                out = model(imgs)
                vl += criterion(out, lbls).item() * imgs.size(0)
                va += (out.argmax(1) == lbls).sum().item()
        va = va / len(val_ds)
        marker = ' ★' if va > best_acc else ''
        if va > best_acc:
            best_acc = va
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        print(f'  E{epoch+1}: train_acc={ta/len(train_ds):.3f} val_acc={va:.3f}{marker}')

    if best_state:
        model.load_state_dict(best_state)
    print(f'\n最佳 val_acc: {best_acc:.3f}')

    # 保存 .pth（先存盘，ONNX 失败也不丢权重）
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pth_path = OUT_DIR / 'usage_cls.pth'
    torch.save(model.state_dict(), pth_path)
    print(f'权重已保存: {pth_path}')

    onnx_path = OUT_DIR / 'usage_cls.onnx'
    labels_path = OUT_DIR / 'usage_labels.json'

    model.eval()
    dummy = torch.randn(1, 3, 224, 224).to(DEVICE)
    torch.onnx.export(
        model, dummy, str(onnx_path),
        input_names=['input'], output_names=['logits'],
        dynamic_axes={'input': {0: 'batch'}, 'logits': {0: 'batch'}},
        opset_version=14,
        dynamo=False,  # legacy exporter，不需要 onnxscript
    )
    with open(labels_path, 'w', encoding='utf-8') as f:
        json.dump({'classes': train_ds.classes}, f, ensure_ascii=False, indent=2)

    size_mb = onnx_path.stat().st_size / 1024 / 1024
    print(f'\nONNX: {onnx_path} ({size_mb:.1f} MB)')
    print(f'Labels: {labels_path} -> {train_ds.classes}')


if __name__ == '__main__':
    main()
