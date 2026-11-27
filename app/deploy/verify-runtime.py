#!/usr/bin/env python3
"""Offline import and computation checks; does not launch services or download models."""
import importlib
import importlib.util
import json
import platform
import sys

MODULES = ['fastapi', 'uvicorn', 'sqlalchemy', 'asyncpg', 'redis', 'httpx',
           'fastapi_users', 'jose', 'jwt', 'PIL', 'numpy', 'cv2', 'zarr',
           'openslide', 'Aslide', 'tifffile', 'h5py', 'pandas', 'scipy',
           'sklearn', 'torch', 'torchvision', 'torchaudio', 'timm', 'transformers',
           'huggingface_hub', 'safetensors', 'open_clip', 'conch.open_clip_custom',
           'segmentation_models_pytorch', 'lifelines', 'torchmetrics', 'omegaconf',
           'nystrom_attention', 'einops_exts', 'jsonschema', 'openai', 'dashscope',
            'lancedb', 'sentence_transformers', 'llama_index.core', 'pymupdf4llm', 'pymupdf.layout', 'markdownify', 'rapidocr', 'onnxruntime',
           'bs4', 'loguru', 'docx', 'markdown_it', 'matplotlib',
           'yaml', 'pydantic', 'packaging', 'json_repair', 'pypdf',
            'joblib', 'threadpoolctl', 'sksurv.metrics', 'pycocotools.mask', 'jieba', 'openpyxl', 'pyarrow']


def main():
    failures = []
    for name in MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failures.append(f'{name}: {type(exc).__name__}: {exc}')
    # Importing kaggle may prompt for credentials; discovery is intentional.
    if importlib.util.find_spec('kaggle') is None:
        failures.append('kaggle is missing')
    if not failures:
        import numpy as np
        import torch
        from sklearn.linear_model import LogisticRegression
        from sksurv.metrics import concordance_index_censored
        from pycocotools import mask
        assert (torch.ones(2, 2) @ torch.ones(2, 2)).sum().item() == 8
        LogisticRegression().fit(np.array([[0], [1], [2], [3]]), [0, 0, 1, 1])
        assert concordance_index_censored(np.array([True,False,True]), np.array([1.,2.,3.]), np.array([3.,2.,1.]))[0] == 1.0
        pixels = np.asfortranarray(np.array([[0,1],[1,1]], dtype=np.uint8))
        assert np.array_equal(mask.decode(mask.encode(pixels)), pixels)
        print(json.dumps({'python': platform.python_version(), 'torch': torch.__version__,
                          'cuda_available': torch.cuda.is_available(), 'imports': len(MODULES), 'status': 'passed'}))
    else:
        print('\n'.join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
