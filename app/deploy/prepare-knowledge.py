"""Provision pinned, open multilingual retrieval models before serving requests."""
import argparse
import json
from pathlib import Path

from huggingface_hub import snapshot_download

MODELS = {
    'embedding': ('intfloat/multilingual-e5-small', '614241f622f53c4eeff9890bdc4f31cfecc418b3'),
    'reranker': ('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1', '1427fd652930e4ba29e8149678df786c240d8825'),
    'training_embedding': ('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                           'e8f8c211226b894fcb81acc59f3b34ba3efd5f42'),
}
IGNORE = ['*.onnx', 'onnx/*', 'openvino/*', '*.h5', '*.msgpack', '*.ot']
WEIGHTS = ('model.safetensors', 'pytorch_model.bin')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='verify the local cache without downloading')
    args = parser.parse_args()
    paths = {}
    for name, (repo, revision) in MODELS.items():
        path = snapshot_download(repo, revision=revision, local_files_only=args.check, ignore_patterns=IGNORE)
        # An interrupted download leaves a snapshot directory without weights.
        if not any((Path(path) / weights).is_file() for weights in WEIGHTS):
            raise SystemExit(f'{repo}@{revision} has no model weights in {path}; rerun without --check')
        paths[name] = path
    print(json.dumps({'ready': True, 'models': paths}, indent=2))


if __name__ == '__main__':
    main()
