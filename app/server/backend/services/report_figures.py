"""Snapshot measured plots and render metric comparisons without invented values."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import textwrap
import threading
from collections import defaultdict
from pathlib import Path

from PIL import Image

from backend.common.config import Config

FONT_DIR = Path(__file__).with_name("report_templates") / "fonts"
PLOT_LOCK = threading.Lock()


def directory(report_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", report_id):
        raise ValueError("Invalid report identifier")
    return Config.get_uploads_dir() / "reports" / report_id / "figures"


def figure_path(report_id: str, filename: str) -> Path:
    if not re.fullmatch(r"figure-[1-6]\.(?:png|svg|pdf|json)", filename):
        raise ValueError("Invalid figure name")
    base = directory(report_id).resolve()
    path = (base / filename).resolve()
    if not path.is_relative_to(base):
        raise ValueError("Invalid figure path")
    return path


def numeric(value, prefix=""):
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict):
            yield from numeric(item, name)
        elif (
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(item)
        ):
            yield name, float(item)


def prepare(report: dict, candidates: list[tuple[Path, str]]) -> list[dict]:
    import matplotlib as mpl
    from matplotlib import font_manager

    # Matplotlib rcParams are process-global. Keep concurrent writing jobs isolated.
    with PLOT_LOCK:
        for path in FONT_DIR.glob("*.ttf"):
            font_manager.fontManager.addfont(str(path))
        with mpl.rc_context(
            {
                "font.family": "Liberation Sans",
                "font.size": 7,
                "axes.labelsize": 7,
                "xtick.labelsize": 6,
                "ytick.labelsize": 6,
                "legend.fontsize": 6,
                "axes.linewidth": 0.6,
                "lines.linewidth": 0.8,
                "xtick.major.width": 0.6,
                "ytick.major.width": 0.6,
                "axes.grid": False,
                "pdf.fonttype": 42,
                "ps.fonttype": 42,
                "svg.fonttype": "none",
                "figure.facecolor": "white",
                "axes.facecolor": "white",
            }
        ):
            return _prepare(report, candidates)


def _prepare(report: dict, candidates: list[tuple[Path, str]]) -> list[dict]:
    folder = directory(report["report_id"])
    folder.mkdir(parents=True, exist_ok=True)
    figures = []
    # Source plots remain provenance assets; scientific plots with numerical data
    # are redrawn below so all generated axes/text use the same Nature style.
    for path, source in candidates[:2]:
        try:
            if any(
                term in path.stem.lower()
                for term in ["roc", "confusion", "loss", "curve", "comparison"]
            ):
                continue  # Redraw scientific plots from data; raster text cannot adopt the requested font.
            if not path.is_file() or path.stat().st_size > 20_000_000:
                continue
            with Image.open(path) as image:
                if image.width * image.height > 40_000_000:
                    continue
                filename = f"figure-{len(figures) + 1}.png"
                image.convert("RGB").save(folder / filename)
            figures.append(
                {
                    "filename": filename,
                    "caption": f"Original experiment image: {path.stem.replace('_', ' ')}.",
                    "source": source,
                    "kind": "original_image",
                    "width_mm": 180,
                }
            )
        except (OSError, ValueError):
            continue
    groups = defaultdict(list)
    for run in report["evidence"]["runs"]:
        if run["status"] != "completed":
            continue
        for metric, value in numeric(run.get("metrics")):
            if any(
                term in metric.lower()
                for term in ["auc", "accuracy", "f1", "c_index", "dice", "iou", "loss"]
            ):
                groups[metric].append(
                    {
                        "run_id": run["run_id"],
                        "method": run.get("name") or run["run_id"],
                        "value": value,
                    }
                )
    # Each plot has one exact metric/split, so train/validation and unlike units never mix.
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    def save(figure, caption, source, kind, data):
        number = len(figures) + 1
        stem = f"figure-{number}"
        figure.savefig(folder / f"{stem}.png", dpi=450)
        figure.savefig(folder / f"{stem}.pdf")
        figure.savefig(folder / f"{stem}.svg")
        svg = (folder / f"{stem}.svg").read_text()
        font = base64.b64encode(
            (FONT_DIR / "LiberationSans-Regular.ttf").read_bytes()
        ).decode()
        svg = svg.replace(
            "<defs>",
            '<defs><style type="text/css">@font-face{font-family:"Liberation Sans";src:url("data:font/ttf;base64,'
            + font
            + '") format("truetype");}</style>',
            1,
        )
        (folder / f"{stem}.svg").write_text(svg)
        (folder / f"{stem}.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
        figures.append(
            {
                "filename": f"{stem}.png",
                "caption": caption,
                "source": source,
                "kind": kind,
                "width_mm": 90,
                "font": "Liberation Sans",
            }
        )

    for analysis in report["evidence"].get("analyses", []):
        charts = analysis.get("chart_data", {})
        for kind in ["roc_curve", "confusion_matrix", "loss_curve"]:
            data = charts.get(kind)
            if not data or len(figures) >= 4:
                continue
            figure = Figure(figsize=(90 / 25.4, 75 / 25.4), layout="constrained")
            FigureCanvasAgg(figure)
            axis = figure.subplots()
            if kind == "roc_curve":
                colors = [
                    "#0072B2",
                    "#D55E00",
                    "#009E73",
                    "#CC79A7",
                    "#E69F00",
                    "#56B4E9",
                    "#444444",
                ]
                plotted = 0
                for index, (label, values) in enumerate(data.get("data", {}).items()):
                    if len(values.get("fpr", [])) != len(
                        values.get("tpr", [])
                    ) or not values.get("fpr"):
                        continue
                    axis.plot(
                        values["fpr"],
                        values["tpr"],
                        color=colors[index % len(colors)],
                        label=str(label),
                    )
                    plotted += 1
                if not plotted:
                    continue
                axis.plot(
                    [0, 1], [0, 1], linestyle="--", color="#777777", linewidth=0.5
                )
                axis.set(
                    xlabel="False positive rate",
                    ylabel="True positive rate",
                    xlim=(0, 1),
                    ylim=(0, 1),
                )
                axis.legend(frameon=False, loc="lower right")
                caption = "Receiver operating characteristic curves from recorded prediction analysis. Curves are reconstructed from stored false-positive and true-positive rates."
            elif kind == "loss_curve":
                series = (
                    data.get("folds", {}) if data.get("is_kfold") else {"Model": data}
                )
                plotted = 0
                colors = ["#0072B2", "#D55E00", "#009E73", "#CC79A7"]
                for index, (label, values) in enumerate(series.items()):
                    epochs = values.get("epochs", [])
                    for key, linestyle in [("loss", "-"), ("val_loss", "--")]:
                        points = values.get(key, [])
                        if (
                            epochs
                            and len(points) == len(epochs)
                            and all(
                                isinstance(v, (int, float)) and math.isfinite(v)
                                for v in points
                            )
                        ):
                            axis.plot(
                                epochs,
                                points,
                                color=colors[index % len(colors)],
                                linestyle=linestyle,
                                label=f"{label}: {key}",
                            )
                            plotted += 1
                if not plotted:
                    continue
                axis.set(xlabel="Epoch", ylabel="Loss")
                axis.legend(frameon=False)
                caption = "Training and validation loss from recorded epoch histories. Solid and dashed curves denote training and validation respectively."
            else:
                import numpy as np

                labels = data.get("classes", [])
                if not labels or len(labels) > 12:
                    continue
                matrix = np.zeros((len(labels), len(labels)))
                for x, y, value in data.get("data", []):
                    matrix[int(y), int(x)] = value
                axis.imshow(matrix, cmap="Blues")
                axis.set(
                    xticks=range(len(labels)),
                    yticks=range(len(labels)),
                    xticklabels=labels,
                    yticklabels=labels,
                    xlabel="Predicted class",
                    ylabel="Recorded class",
                )
                axis.tick_params(axis="x", labelrotation=45)
                for y in range(len(labels)):
                    for x in range(len(labels)):
                        axis.text(
                            x,
                            y,
                            f"{matrix[y, x]:g}",
                            ha="center",
                            va="center",
                            fontsize=6,
                            color="white"
                            if matrix[y, x] > matrix.max() * 0.55
                            else "black",
                        )
                caption = "Confusion matrix reconstructed from recorded class counts. Rows denote recorded classes; columns denote model predictions."
            axis.spines[["top", "right"]].set_visible(False)
            save(figure, caption, analysis["analysis_id"], kind, data)

    ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    for metric, values in ranked[: min(2, 6 - len(figures))]:
        total_values = len(values)
        values = values[:12]
        figure = Figure(
            figsize=(90 / 25.4, min(120, max(55, 7 * len(values) + 25)) / 25.4),
            dpi=450,
            layout="constrained",
        )
        FigureCanvasAgg(figure)
        axis = figure.subplots()
        names = [v["method"] for v in values]
        # Prefer the common-prefix-free method names; keep full names in source data.
        prefix = os.path.commonprefix(names) if len(names) > 1 else ""
        if "-" in prefix:
            prefix = prefix[: prefix.rfind("-") + 1]
        else:
            prefix = ""
        labels = [textwrap.fill(name[len(prefix) :], width=22) for name in names]
        bars = axis.barh(
            labels, [v["value"] for v in values], color="#0072B2", height=0.55
        )
        axis.bar_label(bars, fmt="%.4f", padding=3, fontsize=6)
        axis.set_xlabel(metric, fontsize=7)
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(False)
        axis.set_axisbelow(True)
        axis.margins(x=0.18)
        axis.set_ylim(-0.9, len(values) - 0.1)
        save(
            figure,
            f"Recorded {metric} for {len(values)} of {total_values} completed experiment(s). Each bar is one recorded value; no uncertainty estimate is inferred.",
            ", ".join(v["run_id"] for v in values),
            "metric_comparison",
            {"metric": metric, "values": values},
        )
    return [{**figure, "number": i + 1} for i, figure in enumerate(figures)]


def attach(content: str, figures: list[dict], language='en-US') -> str:
    if not figures:
        return content
    # Generated image locations are controlled by the server, never by the model.
    content = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", content)
    captions = {
        'zh-CN': {'roc_curve': '基于已保存预测分析重建的 ROC 曲线。', 'confusion_matrix': '基于已记录类别计数重建的混淆矩阵；行为实际类别，列为预测类别。', 'loss_curve': '已记录的训练与验证损失；实线为训练，虚线为验证。', 'metric_comparison': '已完成实验的实测指标比较；每根柱表示一个记录值，不据此推断不确定性。'},
        'zh-HK': {'roc_curve': '基於已儲存預測分析重建的 ROC 曲線。', 'confusion_matrix': '基於已記錄類別計數重建的混淆矩陣；行為實際類別，列為預測類別。', 'loss_curve': '已記錄的訓練與驗證損失；實線為訓練，虛線為驗證。', 'metric_comparison': '已完成實驗的實測指標比較；每根柱表示一個記錄值，不據此推斷不確定性。'},
    }
    figure_label = '圖' if language == 'zh-HK' else '图' if language == 'zh-CN' else 'Figure'
    source_label = '來源' if language == 'zh-HK' else '来源' if language == 'zh-CN' else 'Source'
    descriptions = []
    for figure in figures:
        caption = captions.get(language, {}).get(figure.get('kind'), figure['caption'])
        label = f"{figure_label} {figure['number']}. {caption}"
        descriptions.append(f"![{label}](figures/{figure['filename']})\n\n{label} {source_label}: {figure['source']}.")
    block = '\n\n'.join(descriptions)
    match = re.search(
        r"(?ms)^## (?:Results|Experiments and results)\s*\n.*?(?=^## |\Z)", content
    )
    if match:
        return (
            content[: match.end()].rstrip()
            + "\n\n"
            + block
            + "\n\n"
            + content[match.end() :]
        )
    return content + "\n\n## Figures\n\n" + block
