#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
train_classifier.py — MobileNetV2 迁移学习微调，导出 ONNX

用法:
  # 训练照片五分类（label/product/packing_list/packaging）
  python train_classifier.py --kind --epochs 15

  # 训练用途二分类（precheck/supervision）
  python train_classifier.py --usage --epochs 10

  # 只导出已有权重为 ONNX
  python train_classifier.py --export-only --kind

输出:
  kind_classifier.pth / kind_classifier.onnx   ← 五分类
  usage_classifier.pth / usage_classifier.onnx ← 二分类
  labels.json                                  ← 类别映射（推理时用）
"""
import argparse, os, json, time, sys
from pathlib import Path

# 🔴 PyTorch 装在 user site-packages（系统 C:\Python312 禁用了 user site）
sys.path.insert(0, r'C:\Users\Bone\AppData\Roaming\Python\Python312\site-packages')

from PIL import Image, ImageFile
Image.MAX_IMAGE_PIXELS = None  # 解除超大图限制
ImageFile.LOAD_TRUNCATED_IMAGES = True

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torchvision import datasets, models, transforms

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
DATA_ROOT = Path(__file__).parent / 'dataset'
OUT_DIR = Path(__file__).parent / 'outputs'

# 类别定义（与 export_dataset.py 一致）
KIND_CLASSES = ['label', 'packaging', 'packing_list', 'product']
USAGE_CLASSES = ['precheck', 'supervision']


def make_transforms(train=True):
    """数据增强 + 归一化（ImageNet 均值方差）"""
    normalize = transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225])
    if train:
        return transforms.Compose([
            transforms.Resize((256, 256)),
            transforms.RandomCrop(224),
            transforms.RandomHorizontalFlip(),
            transforms.ColorJitter(brightness=0.2, contrast=0.2),
            transforms.ToTensor(),
            normalize,
        ])
    return transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        normalize,
    ])


def build_model(num_classes):
    """MobileNetV2，替换分类头"""
    model = models.mobilenet_v2(weights=models.MobileNet_V2_Weights.IMAGENET1K_V2)
    model.classifier = nn.Sequential(
        nn.Dropout(0.2),
        nn.Linear(model.last_channel, num_classes),
    )
    return model


def train_epoch(model, loader, criterion, optimizer):
    model.train()
    total_loss, correct, total = 0, 0, 0
    for images, labels in loader:
        images, labels = images.to(DEVICE), labels.to(DEVICE)
        optimizer.zero_grad()
        out = model(images)
        loss = criterion(out, labels)
        loss.backward()
        optimizer.step()
        total_loss += loss.item() * images.size(0)
        correct += (out.argmax(1) == labels).sum().item()
        total += images.size(0)
    return total_loss / total, correct / total


@torch.no_grad()
def eval_model(model, loader, criterion):
    model.eval()
    total_loss, correct, total = 0, 0, 0
    for images, labels in loader:
        images, labels = images.to(DEVICE), labels.to(DEVICE)
        out = model(images)
        loss = criterion(out, labels)
        total_loss += loss.item() * images.size(0)
        correct += (out.argmax(1) == labels).sum().item()
        total += images.size(0)
    return total_loss / total, correct / total


def train_task(task_name, classes, data_subdir, epochs):
    """训练一个分类任务"""
    print(f'\n{"="*60}')
    print(f'训练任务: {task_name}')
    print(f'类别: {classes}')
    print(f'设备: {DEVICE}')
    print(f'{"="*60}')

    data_dir = DATA_ROOT / data_subdir
    if not data_dir.exists():
        print(f'错误: 数据目录不存在 {data_dir}')
        print('请先运行: python export_dataset.py')
        return

    # 加载数据
    train_ds = datasets.ImageFolder(str(data_dir / 'train'), transform=make_transforms(train=True))
    val_ds = datasets.ImageFolder(str(data_dir / 'val'), transform=make_transforms(train=False))

    # 确保类别顺序一致
    print(f'\n训练集: {len(train_ds)} 张, 类别: {train_ds.classes}')
    print(f'验证集: {len(val_ds)} 张, 类别: {val_ds.classes}')

    # 类别加权（处理不均衡）
    counts = [0] * len(classes)
    for _, idx in train_ds.samples:
        counts[idx] += 1
    weights = torch.tensor([1.0 / max(c, 1) for c in counts], dtype=torch.float32)
    weights = weights / weights.sum() * len(classes)
    print(f'类别样本数: {counts}, 权重: {[f"{w:.2f}" for w in weights]}')

    train_loader = DataLoader(train_ds, batch_size=32, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=64, shuffle=False, num_workers=0)

    # 构建模型
    model = build_model(len(classes)).to(DEVICE)
    criterion = nn.CrossEntropyLoss(weight=weights.to(DEVICE))

    # Stage 1: 冻结骨干，只训练分类头
    print('\n--- Stage 1: 冻结骨干，训练分类头 (5 epoch) ---')
    for p in model.features.parameters():
        p.requires_grad = False
    optimizer = optim.AdamW(model.classifier.parameters(), lr=1e-3, weight_decay=1e-4)
    for epoch in range(5):
        t0 = time.time()
        tl, ta = train_epoch(model, train_loader, criterion, optimizer)
        vl, va = eval_model(model, val_loader, criterion)
        print(f'  Epoch {epoch+1}/5  loss={tl:.4f} acc={ta:.3f}  val_loss={vl:.4f} val_acc={va:.3f}  ({time.time()-t0:.1f}s)')

    # Stage 2: 解冻最后几层微调
    print('\n--- Stage 2: 解冻骨干最后 20 层，微调 ---')
    for p in model.features[-20:].parameters():
        p.requires_grad = True
    optimizer = optim.AdamW([
        {'params': model.features[-20:].parameters(), 'lr': 1e-5},
        {'params': model.classifier.parameters(), 'lr': 1e-4},
    ], weight_decay=1e-4)

    best_acc = 0
    best_state = None
    for epoch in range(epochs):
        t0 = time.time()
        tl, ta = train_epoch(model, train_loader, criterion, optimizer)
        vl, va = eval_model(model, val_loader, criterion)
        marker = ''
        if va > best_acc:
            best_acc = va
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            marker = ' ★ best'
        print(f'  Epoch {epoch+1}/{epochs}  loss={tl:.4f} acc={ta:.3f}  val_loss={vl:.4f} val_acc={va:.3f}{marker}  ({time.time()-t0:.1f}s)')

    # 恢复最佳权重
    if best_state:
        model.load_state_dict(best_state)
        print(f'\n最佳验证准确率: {best_acc:.3f}')

    # 保存
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pth_path = OUT_DIR / f'{task_name}_classifier.pth'
    torch.save(model.state_dict(), pth_path)
    print(f'模型已保存: {pth_path}')

    # 保存类别映射
    labels = {cls: i for i, cls in enumerate(train_ds.classes)}
    labels_path = OUT_DIR / f'{task_name}_labels.json'
    with open(labels_path, 'w', encoding='utf-8') as f:
        json.dump(labels, f, ensure_ascii=False, indent=2)
    print(f'类别映射: {labels_path}')

    # 导出 ONNX
    onnx_path = OUT_DIR / f'{task_name}_classifier.onnx'
    model.eval()
    dummy = torch.randn(1, 3, 224, 224).to(DEVICE)
    torch.onnx.export(
        model, dummy, str(onnx_path),
        input_names=['input'], output_names=['logits'],
        dynamic_axes={'input': {0: 'batch'}, 'logits': {0: 'batch'}},
        opset_version=14,
        dynamo=False,  # legacy exporter，不需要 onnxscript
    )
    size_mb = onnx_path.stat().st_size / 1024 / 1024
    print(f'ONNX 已导出: {onnx_path} ({size_mb:.1f} MB)')

    return best_acc


def export_onnx(task_name, classes):
    """从已有 .pth 导出 ONNX"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pth_path = OUT_DIR / f'{task_name}_classifier.pth'
    if not pth_path.exists():
        print(f'错误: 权重文件不存在 {pth_path}，请先训练')
        return

    model = build_model(len(classes)).to(DEVICE)
    model.load_state_dict(torch.load(pth_path, map_location=DEVICE))
    model.eval()

    onnx_path = OUT_DIR / f'{task_name}_classifier.onnx'
    dummy = torch.randn(1, 3, 224, 224).to(DEVICE)
    torch.onnx.export(
        model, dummy, str(onnx_path),
        input_names=['input'], output_names=['logits'],
        dynamic_axes={'input': {0: 'batch'}, 'logits': {0: 'batch'}},
        opset_version=14,
        dynamo=False,  # legacy exporter，不需要 onnxscript
    )
    size_mb = onnx_path.stat().st_size / 1024 / 1024
    print(f'ONNX 已导出: {onnx_path} ({size_mb:.1f} MB)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kind', action='store_true', help='训练照片五分类')
    ap.add_argument('--usage', action='store_true', help='训练用途二分类')
    ap.add_argument('--epochs', type=int, default=10, help='微调轮数')
    ap.add_argument('--export-only', action='store_true', help='只导出 ONNX，不训练')
    args = ap.parse_args()

    if not (args.kind or args.usage):
        print('请指定 --kind 或 --usage')
        print('示例: python train_classifier.py --kind --epochs 15')
        return

    if args.kind:
        if args.export_only:
            export_onnx('kind', KIND_CLASSES)
        else:
            train_task('kind', KIND_CLASSES, 'kind', args.epochs)

    if args.usage:
        if args.export_only:
            export_onnx('usage', USAGE_CLASSES)
        else:
            train_task('usage', USAGE_CLASSES, 'usage', args.epochs)


if __name__ == '__main__':
    main()
