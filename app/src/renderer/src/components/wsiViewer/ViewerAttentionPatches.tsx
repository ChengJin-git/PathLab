import { useId, useState } from "react";
import { ArrowDown, ArrowUp, Focus, ImageOff, Info } from "lucide-react";
import {
  getPatchImageUrl,
  type HeatmapData,
  type HeatmapPoint,
} from "../../api/heatmap";
import type { Geometry } from "../../api/viewer";
import { Tooltip } from "../ui/tooltip";
import { useViewerText } from "./viewerText";

function formatAttention(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  return magnitude < 0.0001 || magnitude >= 10000
    ? value.toExponential(2)
    : String(Number(value.toPrecision(4)));
}

function AttentionPatch({
  id,
  patch,
  size,
  rank,
  group,
  active,
  onFocus,
}: {
  id: string;
  patch: HeatmapPoint;
  size: number;
  rank: number;
  group: string;
  active: boolean;
  onFocus: () => void;
}) {
  const { t } = useViewerText();
  const [failed, setFailed] = useState(false);
  const score = formatAttention(patch.raw_weight);
  const label = `${group} ${rank}`;
  return (
    <Tooltip
      content={
        <>
          {t("attentionScore")}: {patch.raw_weight.toPrecision(7)}
          <br />
          {t("position")}: {patch.x}, {patch.y}
        </>
      }
    >
      <button
        className="viewer-attention-patch"
        aria-label={label}
        aria-pressed={active}
        onClick={onFocus}
      >
        <span className="viewer-attention-image">
          {failed ? (
            <ImageOff size={16} aria-label={t("patchUnavailable")} />
          ) : (
            <img
              src={getPatchImageUrl(id, patch.x, patch.y, size, 160)}
              alt=""
              loading="lazy"
              decoding="async"
              onError={() => setFailed(true)}
            />
          )}
          <span className="viewer-attention-rank">{rank}</span>
          <Focus size={17} className="viewer-attention-focus" aria-hidden />
        </span>
        <span className="viewer-attention-score">{score}</span>
      </button>
    </Tooltip>
  );
}

export function ViewerAttentionPatches({
  id,
  heatmap,
  onFocus,
}: {
  id: string;
  heatmap: HeatmapData;
  onFocus: (region: Geometry) => void;
}) {
  const { t } = useViewerText();
  const headingId = useId();
  const [active, setActive] = useState<string>();
  return (
    <section className="viewer-attention" aria-label={t("attentionRegions")}>
      <div className="viewer-attention-description">
        <span>{t("attentionBrowseHint")}</span>
        <Tooltip content={t("attentionScoreHint")}>
          <button
            className="viewer-attention-info"
            aria-label={t("attentionScoreHint")}
          >
            <Info size={13} />
          </button>
        </Tooltip>
      </div>
      {(
        [
          ["high", "highAttention", heatmap.top_patches, ArrowUp],
          ["low", "lowAttention", heatmap.bottom_patches, ArrowDown],
        ] as const
      ).map(
        ([group, key, patches, Icon]) =>
          patches.length > 0 && (
            <section
              className="viewer-attention-group"
              data-attention={group}
              aria-labelledby={`${headingId}-${group}`}
              key={group}
            >
              <header className="viewer-attention-heading">
                <h3 id={`${headingId}-${group}`}>
                  <Icon size={14} />
                  {t(key)}
                </h3>
                <span>{Math.min(10, patches.length)}</span>
              </header>
              <div className="viewer-attention-grid">
                {patches.slice(0, 10).map((patch, index) => (
                  <AttentionPatch
                    key={`${patch.index}:${patch.x}:${patch.y}`}
                    id={id}
                    patch={patch}
                    size={heatmap.patch_size}
                    rank={index + 1}
                    group={t(key)}
                    active={active === `${group}:${patch.index}`}
                    onFocus={() => {
                      setActive(`${group}:${patch.index}`);
                      onFocus({
                        type: "rect",
                        x: patch.x,
                        y: patch.y,
                        width: Math.min(
                          heatmap.patch_size,
                          heatmap.slide_width - patch.x,
                        ),
                        height: Math.min(
                          heatmap.patch_size,
                          heatmap.slide_height - patch.y,
                        ),
                      });
                    }}
                  />
                ))}
              </div>
            </section>
          ),
      )}
    </section>
  );
}
