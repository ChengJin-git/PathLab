import sys
sys.path.insert(0, '/storage/jmabq/PathStudio/nnUNet')
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from skimage.io import imread


def visualize_segmentation(img_path, gt_path, pred_path, output_path, label_mapper):


    # 读取图像和标签
    img = imread(img_path)
    gt = imread(gt_path)
    pred = imread(pred_path)

    # 创建颜色映射
    num_classes = len(label_mapper)
    colors = plt.cm.get_cmap('tab20', num_classes).colors
    cmap = ListedColormap(colors)

    # 创建子图
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    axes[0].imshow(img)
    axes[0].set_title('Original Image')
    axes[0].axis('off')

    axes[1].imshow(gt, cmap=cmap, vmin=0, vmax=num_classes - 1)
    axes[1].set_title('Ground Truth')
    axes[1].axis('off')

    axes[2].imshow(pred, cmap=cmap, vmin=0, vmax=num_classes - 1)
    axes[2].set_title('Prediction')
    axes[2].axis('off')

    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    

def visualize_overlay(img_path, pred_path, output_path, alpha=0.5):
    # 读取图像和预测标签
    img = imread(img_path)
    pred = imread(pred_path)

    # 创建颜色映射
    num_classes = np.max(pred) + 1
    colors = plt.cm.get_cmap('tab20', num_classes).colors
    cmap = ListedColormap(colors)

    # 创建叠加图
    plt.figure(figsize=(8, 8))
    plt.imshow(img)
    plt.imshow(pred, cmap=cmap, alpha=alpha, vmin=0, vmax=num_classes - 1)
    plt.title('Overlay of Prediction on Image')
    plt.axis('off')

    plt.savefig(output_path)
    plt.close()


labels = {
    "background": 0,
    
    "tumor": 1,
    "stroma": 2,
    "lymphocytic_infiltrate": 3,
    "necrosis_or_debris": 4,
    "glandular_secretions": 5,
    "blood": 6,
    "exclude": 7,
    "metaplasia_NOS": 8,
    "fat": 9,
    "plasma_cells": 10,
    "other_immune_infiltrate": 11,
    "mucoid_material": 12,
    "normal_acinus_or_duct": 13,
    "lymphatics": 14,
    "undetermined": 15,
    "nerve": 16,
    "skin_adnexa": 17,
    "blood_vessel": 18,
    "angioinvasion": 19,
    "dcis": 20,
    "other": 21
}

img_file = '/storage/jmabq/data/nnUNet_Data/Dataset001_BCSS/imagesTs/TCGA-A2-A0D0-DX1_xmin68482_ymin39071_MPP-0.2500_0000.png'
gt_file = '/storage/jmabq/data/nnUNet_Data/Dataset001_BCSS/labelsTs/TCGA-A2-A0D0-DX1_xmin68482_ymin39071_MPP-0.2500.png'
pred_file = '/storage/jmabq/data/nnUNet_Results/Dataset001_BCSS/nnUNetTrainer__nnUNetResEncUNetLPlans__2d/predictions/4/TCGA-A2-A0D0-DX1_xmin68482_ymin39071_MPP-0.2500.png'

if __name__ == '__main__':
    # 可视化对比：原始图像、真实标签、预测结果
    print("生成对比可视化...")
    visualize_segmentation(
        img_path=img_file,
        gt_path=gt_file,
        pred_path=pred_file,
        output_path='visualization_comparison.png',
        label_mapper=labels
    )
    
    # 可视化叠加效果
    print("生成叠加可视化...")
    visualize_overlay(
        img_path=img_file,
        pred_path=pred_file,
        output_path='visualization_overlay.png',
        alpha=0.5
    )
    
    print("\n完成！生成的文件:")
    print("  - visualization_comparison.png (对比图)")
    print("  - visualization_overlay.png (叠加图)")


