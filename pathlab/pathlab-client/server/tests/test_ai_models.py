import pytest
import torch


DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class TestGpuEnvironment:
    def test_cuda_is_available(self):
        assert torch.cuda.is_available(), (
            "No CUDA GPU detected — subsequent GPU tests will fail"
        )

    def test_at_least_one_gpu(self):
        assert torch.cuda.device_count() >= 1

    def test_tensor_allocation_on_gpu(self):
        t = torch.zeros(4, 4, device=DEVICE)
        assert t.device.type == "cuda"

    def test_basic_matmul_on_gpu(self):
        a = torch.randn(16, 16, device=DEVICE)
        b = torch.randn(16, 16, device=DEVICE)
        c = a @ b
        assert c.shape == (16, 16)
        assert c.device.type == "cuda"


class TestExtractorRegistry:
    def test_list_extractors_returns_all_known_names(self):
        from backend.ai.extractors.registry import list_extractors

        names = list_extractors()
        for expected in [
            "resnet50",
            "vit_l_16",
            "conch",
            "uni",
            "virchow",
            "plip",
            "phikon",
        ]:
            assert expected in names, f"'{expected}' missing from extractor registry"

    def test_get_available_extractors_includes_metadata(self):
        from backend.ai.extractors.registry import get_available_extractors

        extractors = get_available_extractors()
        assert len(extractors) >= 10
        for entry in extractors:
            assert "id" in entry
            assert "name" in entry
            assert "description" in entry

    def test_extractor_supports_spatial_resnet50(self):
        from backend.ai.extractors.registry import extractor_supports_spatial

        assert extractor_supports_spatial("resnet50") is False

    def test_extractor_supports_spatial_conch(self):
        from backend.ai.extractors.registry import extractor_supports_spatial

        assert extractor_supports_spatial("conch") is True

    def test_extractor_supports_spatial_uni(self):
        from backend.ai.extractors.registry import extractor_supports_spatial

        assert extractor_supports_spatial("uni") is True

    def test_unknown_extractor_raises_value_error(self):
        from backend.ai.extractors.registry import get_extractor

        with pytest.raises((ValueError, ImportError)):
            get_extractor("nonexistent_extractor_xyz")

    def test_lazy_class_resolution_conch(self):
        from backend.ai.extractors.registry import _resolve_extractor_class

        cls = _resolve_extractor_class("conch")
        assert cls is not None
        assert hasattr(cls, "build")

    def test_lazy_class_resolution_uni(self):
        from backend.ai.extractors.registry import _resolve_extractor_class

        cls = _resolve_extractor_class("uni")
        assert cls is not None
        assert hasattr(cls, "build")

    def test_lazy_class_resolution_virchow(self):
        from backend.ai.extractors.registry import _resolve_extractor_class

        cls = _resolve_extractor_class("virchow")
        assert cls is not None

    def test_lazy_class_resolution_phikon(self):
        from backend.ai.extractors.registry import _resolve_extractor_class

        cls = _resolve_extractor_class("phikon")
        assert cls is not None

    def test_lazy_class_resolution_plip(self):
        from backend.ai.extractors.registry import _resolve_extractor_class

        cls = _resolve_extractor_class("plip")
        assert cls is not None

    def test_lazy_class_resolution_all_registered(self):
        from backend.ai.extractors.registry import (
            _EXTRACTOR_LAZY_REGISTRY,
            _resolve_extractor_class,
        )

        for name in _EXTRACTOR_LAZY_REGISTRY:
            cls = _resolve_extractor_class(name)
            assert cls is not None, f"Could not resolve class for '{name}'"
            assert hasattr(cls, "build"), f"'{name}' class missing build() classmethod"


class TestExtractorTransforms:
    def test_imagenet_mean_std_values(self):
        from backend.ai.extractors.transforms import IMAGENET_MEAN, IMAGENET_STD

        assert len(IMAGENET_MEAN) == 3
        assert len(IMAGENET_STD) == 3
        assert all(0 < v < 1 for v in IMAGENET_MEAN)
        assert all(0 < v < 1 for v in IMAGENET_STD)

    def test_get_default_transforms_eval_is_callable(self):
        from backend.ai.extractors.transforms import get_default_transforms

        t = get_default_transforms(image_size=224, mode="eval")
        assert callable(t)

    def test_get_default_transforms_train_is_callable(self):
        from backend.ai.extractors.transforms import get_default_transforms

        t = get_default_transforms(image_size=224, mode="train")
        assert callable(t)

    def test_transforms_output_shape(self):
        from backend.ai.extractors.transforms import get_default_transforms
        from PIL import Image
        import numpy as np

        t = get_default_transforms(image_size=224, mode="eval")
        img = Image.fromarray(np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8))
        tensor = t(img)
        assert tensor.shape == (3, 224, 224)


class TestResNet50ExtractorGpu:
    @pytest.fixture(scope="class")
    def model(self):
        from backend.ai.extractors.resnet50 import ResNet50Extractor

        m = ResNet50Extractor(pretrained=False)
        m.eval()
        return m.to(DEVICE)

    def test_output_dim_is_2048(self, model):
        assert model.output_dim == 2048

    def test_forward_shape_single_image(self, model):
        x = torch.randn(1, 3, 224, 224, device=DEVICE)
        with torch.no_grad():
            out = model(x)
        assert out.shape == (1, 2048)

    def test_forward_shape_batch(self, model):
        x = torch.randn(4, 3, 224, 224, device=DEVICE)
        with torch.no_grad():
            out = model(x)
        assert out.shape == (4, 2048)

    def test_output_is_finite(self, model):
        x = torch.randn(2, 3, 224, 224, device=DEVICE)
        with torch.no_grad():
            out = model(x)
        assert torch.isfinite(out).all()

    def test_output_is_on_gpu(self, model):
        x = torch.randn(1, 3, 224, 224, device=DEVICE)
        with torch.no_grad():
            out = model(x)
        assert out.device.type == "cuda"

    def test_different_inputs_produce_different_outputs(self, model):
        x1 = torch.randn(1, 3, 224, 224, device=DEVICE)
        x2 = torch.randn(1, 3, 224, 224, device=DEVICE)
        with torch.no_grad():
            o1 = model(x1)
            o2 = model(x2)
        assert not torch.allclose(o1, o2)

    def test_build_classmethod(self):
        from backend.ai.extractors.resnet50 import ResNet50Extractor

        m = ResNet50Extractor.build(pretrained=False)
        assert isinstance(m, ResNet50Extractor)
        assert m.output_dim == 2048

    def test_eval_transforms_callable(self, model):
        t = model.get_transforms(mode="eval")
        assert callable(t)


class TestViTL16ExtractorGpu:
    @pytest.fixture(scope="class")
    def model(self):
        from backend.ai.extractors.vit_l_16 import ViTL16Extractor

        m = ViTL16Extractor(pretrained=False)
        m.eval()
        return m.to(DEVICE)

    def test_output_dim_is_1024(self, model):
        assert model.output_dim == 1024

    def test_forward_shape_single_image(self, model):
        x = torch.randn(1, 3, 224, 224, device=DEVICE)
        with torch.no_grad():
            out = model(x)
        assert out.shape == (1, 1024)

    def test_forward_shape_batch(self, model):
        x = torch.randn(2, 3, 224, 224, device=DEVICE)
        with torch.no_grad():
            out = model(x)
        assert out.shape == (2, 1024)

    def test_output_is_finite(self, model):
        x = torch.randn(1, 3, 224, 224, device=DEVICE)
        with torch.no_grad():
            out = model(x)
        assert torch.isfinite(out).all()

    def test_output_on_gpu(self, model):
        x = torch.randn(1, 3, 224, 224, device=DEVICE)
        with torch.no_grad():
            out = model(x)
        assert out.device.type == "cuda"


class TestAggregatorRegistry:
    def test_list_aggregators_returns_all(self):
        from backend.ai.aggregators.registry import list_aggregators

        names = list_aggregators()
        for expected in [
            "abmil",
            "meanmil",
            "maxmil",
            "dsmil",
            "dtfdmil",
            "clam_sb",
            "clam_mb",
            "transmil",
        ]:
            assert expected in names

    def test_unknown_aggregator_raises(self):
        from backend.ai.aggregators.registry import get_aggregator

        with pytest.raises(ValueError):
            get_aggregator("nonexistent_agg", in_dim=256, num_classes=2)


@pytest.mark.parametrize(
    "agg_name,in_dim,num_classes,n_patches",
    [
        ("abmil", 256, 2, 50),
        ("abmil", 1024, 3, 100),
        ("meanmil", 256, 2, 50),
        ("maxmil", 256, 2, 50),
        ("dsmil", 512, 3, 64),
        ("dtfdmil", 512, 2, 64),
        ("clam_sb", 512, 2, 64),
        ("clam_mb", 512, 3, 64),
        ("transmil", 512, 2, 64),
    ],
)
def test_aggregator_forward_gpu(agg_name, in_dim, num_classes, n_patches):
    from backend.ai.aggregators.registry import get_aggregator

    model = get_aggregator(agg_name, in_dim=in_dim, num_classes=num_classes)
    model.eval()
    model = model.to(DEVICE)
    H = torch.randn(n_patches, in_dim, device=DEVICE)
    with torch.no_grad():
        logits, attention = model(H)
    assert logits.shape[-1] == num_classes, f"{agg_name}: logits shape mismatch"
    assert torch.isfinite(logits).all(), f"{agg_name}: logits contain non-finite values"


class TestABMILAttention:
    @pytest.fixture(scope="class")
    def model(self):
        from backend.ai.aggregators.abmil import ABMILAggregator

        m = ABMILAggregator(in_dim=256, num_classes=2)
        m.eval()
        return m.to(DEVICE)

    def test_attention_sums_to_one(self, model):
        H = torch.randn(30, 256, device=DEVICE)
        with torch.no_grad():
            _, attn = model(H)
        assert abs(attn.sum().item() - 1.0) < 1e-5

    def test_attention_all_non_negative(self, model):
        H = torch.randn(30, 256, device=DEVICE)
        with torch.no_grad():
            _, attn = model(H)
        assert (attn >= 0).all()

    def test_attention_length_equals_n_patches(self, model):
        n = 45
        H = torch.randn(n, 256, device=DEVICE)
        with torch.no_grad():
            _, attn = model(H)
        assert attn.shape[0] == n

    def test_forward_with_raw_attention(self, model):
        H = torch.randn(20, 256, device=DEVICE)
        with torch.no_grad():
            logits, attn, raw_attn = model.forward_with_raw_attention(H)
        assert logits.shape == (1, 2)
        assert attn.shape == (20,)
        assert raw_attn.shape == (20,)


class TestClassifierRegistry:
    def test_list_classifiers(self):
        from backend.ai.classifiers.registry import list_classifiers

        names = list_classifiers()
        for expected in ["linear", "mlp", "attention"]:
            assert expected in names

    def test_unknown_classifier_raises(self):
        from backend.ai.classifiers.registry import get_classifier

        with pytest.raises(ValueError):
            get_classifier("nonexistent_clf", num_classes=2)


@pytest.mark.parametrize(
    "clf_name,in_dim,num_classes,batch",
    [
        ("linear", 256, 2, 8),
        ("linear", 1024, 5, 4),
        ("mlp", 256, 3, 8),
        ("attention", 512, 2, 16),
    ],
)
def test_classifier_forward_gpu(clf_name, in_dim, num_classes, batch):
    from backend.ai.classifiers.registry import get_classifier

    model = get_classifier(clf_name, num_classes=num_classes, in_dim=in_dim)
    model.eval()
    model = model.to(DEVICE)
    x = torch.randn(batch, in_dim, device=DEVICE)
    with torch.no_grad():
        out = model(x)
    assert out.shape[-1] == num_classes, f"{clf_name}: output shape mismatch"
    assert torch.isfinite(out).all(), f"{clf_name}: output contains non-finite values"
