from __future__ import annotations

from pathlib import Path

import timm

from .weight_loading import first_existing_weight_file, load_state_dict_file, unwrap_state_dict


def _normalize_h_optimus_state_dict(backbone, state):
    state = dict(state)
    pos_embed = state.get("pos_embed")
    if pos_embed is not None and pos_embed.shape != backbone.pos_embed.shape:
        num_prefix = getattr(backbone, "num_prefix_tokens", 1)
        if pos_embed.shape[1] + num_prefix == backbone.pos_embed.shape[1]:
            merged = backbone.pos_embed.detach().clone()
            merged[:, num_prefix:] = pos_embed
            state["pos_embed"] = merged
    return state


def build_h_optimus_backbone(model_dir: str | Path):
    weight_path = first_existing_weight_file(model_dir)
    backbone = timm.create_model(
        "vit_giant_patch14_dinov2",
        pretrained=False,
        img_size=224,
        num_classes=0,
        global_pool="token",
        reg_tokens=4,
        init_values=1e-5,
        dynamic_img_size=False,
    )
    state = _normalize_h_optimus_state_dict(
        backbone,
        unwrap_state_dict(load_state_dict_file(weight_path)),
    )
    backbone.load_state_dict(state, strict=True)
    backbone.eval()
    return backbone
