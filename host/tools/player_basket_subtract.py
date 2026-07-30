#!/usr/bin/env python3
"""Subtract a basket-only BMI30 player recording from a tag recording.

The output keeps the player .npz layout, so it can be loaded by the BMI30 web
player as another raw recording.  The subtraction is intentionally based on a
low-frequency basket model: the model is matched per channel/phase, then the
smooth basket component is subtracted while the remaining signal is re-centered
around 32768.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np


BASELINE_DEFAULT = 32768.0


def _as_scalar_text(data: np.lib.npyio.NpzFile, key: str, default: str = "") -> str:
    if key not in data.files:
        return default
    try:
        return str(np.asarray(data[key]).reshape(-1)[0])
    except Exception:
        return default


def _moving_average_rows(values: np.ndarray, window: int) -> np.ndarray:
    window = int(window)
    if window <= 1:
        return np.asarray(values, dtype=np.float64)
    if window % 2 == 0:
        window += 1
    pad = window // 2
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("expected a 2D samples array")
    padded = np.pad(arr, ((0, 0), (pad, pad)), mode="edge")
    csum = np.cumsum(padded, axis=1, dtype=np.float64)
    csum = np.concatenate([np.zeros((arr.shape[0], 1), dtype=np.float64), csum], axis=1)
    return (csum[:, window:] - csum[:, :-window]) / float(window)


def _normalize_rows(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    arr = arr - np.mean(arr, axis=1, keepdims=True)
    denom = np.sqrt(np.sum(arr * arr, axis=1, keepdims=True))
    return arr / np.maximum(denom, 1e-9)


def _fit_affine(reference: np.ndarray, target: np.ndarray) -> tuple[float, float]:
    ref = np.asarray(reference, dtype=np.float64)
    tgt = np.asarray(target, dtype=np.float64)
    ref0 = ref - float(np.mean(ref))
    tgt0 = tgt - float(np.mean(tgt))
    denom = float(np.dot(ref0, ref0))
    if denom <= 1e-9:
        return 1.0, float(np.mean(tgt) - np.mean(ref))
    scale = float(np.dot(ref0, tgt0) / denom)
    if not math.isfinite(scale):
        scale = 1.0
    scale = max(0.25, min(4.0, scale))
    offset = float(np.mean(tgt) - scale * np.mean(ref))
    if not math.isfinite(offset):
        offset = 0.0
    return scale, offset


def _weighted_match_models(
    target_lp: np.ndarray,
    basket_lp: np.ndarray,
    k: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return low-pass basket models, representative match indexes, distances."""
    if len(basket_lp) == 0:
        raise ValueError("basket group has no frames")
    k = max(1, min(int(k), len(basket_lp)))
    target_feat = _normalize_rows(target_lp)
    basket_feat = _normalize_rows(basket_lp)
    sim = target_feat @ basket_feat.T
    if k == 1:
        match_idx = np.argmax(sim, axis=1).astype(np.int32)
        model = basket_lp[match_idx].astype(np.float64, copy=True)
        dist = (1.0 - sim[np.arange(len(target_lp)), match_idx]).astype(np.float64)
        return model, match_idx, dist

    # argpartition keeps this cheap and avoids a SciPy/sklearn dependency.
    part = np.argpartition(-sim, kth=k - 1, axis=1)[:, :k]
    row = np.arange(len(target_lp))[:, None]
    chosen_sim = sim[row, part]
    order = np.argsort(-chosen_sim, axis=1)
    chosen_idx = part[row, order]
    chosen_sim = chosen_sim[row, order]
    best_idx = chosen_idx[:, 0].astype(np.int32)
    best_dist = (1.0 - chosen_sim[:, 0]).astype(np.float64)
    weights = np.exp((chosen_sim - chosen_sim[:, :1]) * 12.0)
    weights = weights / np.maximum(np.sum(weights, axis=1, keepdims=True), 1e-12)
    model = np.einsum("nk,nkl->nl", weights, basket_lp[chosen_idx])
    return model.astype(np.float64), best_idx, best_dist


def _subtract_match(
    tag_samples: np.ndarray,
    tag_channels: np.ndarray,
    tag_phases: np.ndarray,
    basket_samples: np.ndarray,
    basket_channels: np.ndarray,
    basket_phases: np.ndarray,
    *,
    baseline: float,
    window: int,
    match_k: int,
    channels_to_process: set[int],
) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, Any]]:
    tag_raw = np.asarray(tag_samples, dtype=np.float64)
    basket_raw = np.asarray(basket_samples, dtype=np.float64)
    tag_lp = _moving_average_rows(tag_raw, window)
    basket_lp = _moving_average_rows(basket_raw, window)

    out = tag_raw.copy()
    match_idx = np.full(len(tag_raw), -1, dtype=np.int32)
    match_dist = np.full(len(tag_raw), np.nan, dtype=np.float64)
    fit_scale = np.full(len(tag_raw), np.nan, dtype=np.float64)
    fit_offset = np.full(len(tag_raw), np.nan, dtype=np.float64)
    model_rms = np.full(len(tag_raw), np.nan, dtype=np.float64)
    group_report: dict[str, Any] = {}

    for ch in (0, 1):
        for ph in (0, 1):
            tag_idx = np.flatnonzero((tag_channels == ch) & (tag_phases == ph))
            basket_idx = np.flatnonzero((basket_channels == ch) & (basket_phases == ph))
            key = f"ch{ch}_ph{ph}"
            if ch not in channels_to_process:
                group_report[key] = {
                    "target": int(len(tag_idx)),
                    "basket": int(len(basket_idx)),
                    "status": "skipped_channel",
                }
                continue
            if len(tag_idx) == 0:
                group_report[key] = {"target": 0, "basket": int(len(basket_idx)), "status": "empty_target"}
                continue
            if len(basket_idx) == 0:
                out[tag_idx] = tag_raw[tag_idx]
                group_report[key] = {"target": int(len(tag_idx)), "basket": 0, "status": "missing_basket"}
                continue

            model_lp, best_local, dist = _weighted_match_models(
                tag_lp[tag_idx],
                basket_lp[basket_idx],
                match_k,
            )
            for row_no, idx in enumerate(tag_idx):
                scale, offset = _fit_affine(model_lp[row_no], tag_lp[idx])
                model = scale * model_lp[row_no] + offset
                out[idx] = tag_raw[idx] - model + baseline
                match_idx[idx] = int(basket_idx[int(best_local[row_no])])
                match_dist[idx] = float(dist[row_no])
                fit_scale[idx] = scale
                fit_offset[idx] = offset
                model_rms[idx] = float(np.sqrt(np.mean((model - baseline) ** 2)))

            group_report[key] = {
                "target": int(len(tag_idx)),
                "basket": int(len(basket_idx)),
                "status": "ok",
                "median_best_distance": float(np.nanmedian(dist)),
                "median_scale": float(np.nanmedian(fit_scale[tag_idx])),
                "median_model_rms": float(np.nanmedian(model_rms[tag_idx])),
            }

    out_u16 = np.clip(np.rint(out), 0, 65535).astype(np.uint16)
    arrays = {
        "basket_match_index": match_idx,
        "basket_match_distance": match_dist,
        "basket_fit_scale": fit_scale,
        "basket_fit_offset": fit_offset,
        "basket_model_rms": model_rms,
    }
    return out_u16, arrays, group_report


def _load_labels(data: np.lib.npyio.NpzFile) -> dict[str, Any]:
    if "user_labels_json" not in data.files:
        return {}
    try:
        raw = str(np.asarray(data["user_labels_json"]).reshape(-1)[0] or "{}")
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _label_mask(data: np.lib.npyio.NpzFile, mode: str = "exact") -> np.ndarray:
    labels = _load_labels(data)
    n = int(len(np.asarray(data["lengths"])))
    mask = np.zeros(n, dtype=bool)
    idxs: list[int] = []
    for item in labels.get("marks", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("mark", "")).strip().lower() != "tag":
            continue
        try:
            idx = int(item.get("packet_idx", -1))
        except Exception:
            idx = -1
        if 0 <= idx < n:
            idxs.append(idx)
            if mode == "exact":
                mask[idx] = True
    if mode == "span" and idxs:
        lo = max(0, min(idxs))
        hi = min(n - 1, max(idxs))
        mask[lo : hi + 1] = True
    return mask


def _channels_from_arg(value: str) -> set[int]:
    raw = str(value or "both").strip().lower()
    if raw in ("both", "all", "*"):
        return {0, 1}
    if raw in ("upper", "u", "0", "adc0", "ch0"):
        return {0}
    if raw in ("lower", "l", "1", "adc1", "ch1"):
        return {1}
    raise ValueError("channel must be upper, lower, or both")


def _rms(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean(arr * arr)))


def _summarize_energy(
    samples: np.ndarray,
    channels: np.ndarray,
    label_mask: np.ndarray,
    *,
    baseline: float,
    window: int,
) -> dict[str, Any]:
    raw = np.asarray(samples, dtype=np.float64)
    lp = _moving_average_rows(raw, window)
    hf = raw - lp
    slow = lp - baseline
    out: dict[str, Any] = {}
    for ch in (0, 1):
        ch_mask = channels == ch
        for name, mask in (
            ("all", ch_mask),
            ("tag", ch_mask & label_mask),
            ("not_tag", ch_mask & ~label_mask),
        ):
            key = f"ch{ch}_{name}"
            if not np.any(mask):
                continue
            out[key] = {
                "frames": int(np.sum(mask)),
                "slow_rms": _rms(slow[mask]),
                "hf_rms": _rms(hf[mask]),
                "total_rms": _rms(raw[mask] - baseline),
            }
    return out


def _copy_npz_arrays(data: np.lib.npyio.NpzFile) -> dict[str, np.ndarray]:
    return {name: np.asarray(data[name]) for name in data.files}


def _update_embedded_labels(arrays: dict[str, np.ndarray], output_name: str, report: dict[str, Any]) -> None:
    raw = arrays.get("user_labels_json")
    if raw is None:
        return
    try:
        payload = json.loads(str(np.asarray(raw).reshape(-1)[0] or "{}"))
        if not isinstance(payload, dict):
            return
        payload["source_file"] = output_name
        payload["updated_at"] = float(_dt.datetime.now().timestamp())
        payload["updated_iso"] = _dt.datetime.now().isoformat(timespec="seconds")
        payload["basket_subtraction"] = {
            "method": report.get("method"),
            "target_file": report.get("target_file"),
            "basket_file": report.get("basket_file"),
            "smooth_window": report.get("smooth_window"),
            "baseline": report.get("baseline"),
            "match_k": report.get("match_k"),
            "channel": report.get("channel"),
        }
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        arrays["user_labels_schema"] = np.array([2], dtype=np.uint16)
        arrays["user_labels_json"] = np.array([text], dtype=f"U{max(1, len(text))}")
    except Exception:
        return


def run(args: argparse.Namespace) -> dict[str, Any]:
    target_path = Path(args.target).expanduser().resolve()
    basket_path = Path(args.basket).expanduser().resolve()
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = target_path.with_name(
            f"{target_path.stem}_minus_basket_{basket_path.stem.replace('player_raw_', '')}.npz"
        )

    with np.load(target_path, allow_pickle=False) as target, np.load(basket_path, allow_pickle=False) as basket:
        required = ("samples", "lengths", "channels", "phases")
        for key in required:
            if key not in target.files:
                raise ValueError(f"target recording missing {key!r}")
            if key not in basket.files:
                raise ValueError(f"basket recording missing {key!r}")

        tag_samples = np.asarray(target["samples"], dtype=np.uint16)
        basket_samples = np.asarray(basket["samples"], dtype=np.uint16)
        if tag_samples.ndim != 2 or basket_samples.ndim != 2:
            raise ValueError("samples arrays must be 2D")
        if tag_samples.shape[1] != basket_samples.shape[1]:
            raise ValueError(
                f"sample width mismatch: target={tag_samples.shape[1]} basket={basket_samples.shape[1]}"
            )

        target_channels = np.asarray(target["channels"], dtype=np.uint8)
        target_phases = np.asarray(target["phases"], dtype=np.uint8)
        basket_channels = np.asarray(basket["channels"], dtype=np.uint8)
        basket_phases = np.asarray(basket["phases"], dtype=np.uint8)
        channels_to_process = _channels_from_arg(args.channel)
        label_mask = _label_mask(target, mode=str(args.label_mask))
        before_energy = _summarize_energy(
            tag_samples,
            target_channels,
            label_mask,
            baseline=float(args.baseline),
            window=int(args.window),
        )

        residual, extra_arrays, group_report = _subtract_match(
            tag_samples,
            target_channels,
            target_phases,
            basket_samples,
            basket_channels,
            basket_phases,
            baseline=float(args.baseline),
            window=int(args.window),
            match_k=int(args.match_k),
            channels_to_process=channels_to_process,
        )
        after_energy = _summarize_energy(
            residual,
            target_channels,
            label_mask,
            baseline=float(args.baseline),
            window=int(args.window),
        )

        report = {
            "method": "matched_low_frequency_subtraction",
            "target_file": target_path.name,
            "basket_file": basket_path.name,
            "output_file": output_path.name,
            "created_iso": _dt.datetime.now().isoformat(timespec="seconds"),
            "smooth_window": int(args.window),
            "baseline": float(args.baseline),
            "match_k": int(args.match_k),
            "channel": str(args.channel),
            "processed_channels": sorted(int(x) for x in channels_to_process),
            "label_mask": str(args.label_mask),
            "target_frames": int(tag_samples.shape[0]),
            "basket_frames": int(basket_samples.shape[0]),
            "sample_width": int(tag_samples.shape[1]),
            "tag_label_frames": int(np.sum(label_mask)),
            "groups": group_report,
            "energy_before": before_energy,
            "energy_after": after_energy,
        }

        arrays = _copy_npz_arrays(target)
        arrays["samples"] = residual
        arrays["source"] = np.array(["basket_subtracted_raw"], dtype="U32")
        arrays["created_at"] = np.array([_dt.datetime.now().isoformat(timespec="seconds")], dtype="U32")
        arrays["basket_subtraction_schema"] = np.array([1], dtype=np.uint16)
        arrays["basket_subtraction_method"] = np.array([report["method"]], dtype="U48")
        arrays["basket_subtraction_target"] = np.array([target_path.name], dtype=f"U{len(target_path.name)}")
        arrays["basket_subtraction_basket"] = np.array([basket_path.name], dtype=f"U{len(basket_path.name)}")
        arrays["basket_subtraction_window"] = np.array([int(args.window)], dtype=np.int32)
        arrays["basket_subtraction_match_k"] = np.array([int(args.match_k)], dtype=np.int32)
        arrays["basket_subtraction_channel"] = np.array([str(args.channel)], dtype=f"U{max(1, len(str(args.channel)))}")
        arrays["basket_subtraction_baseline"] = np.array([float(args.baseline)], dtype=np.float64)
        arrays["basket_subtraction_report_json"] = np.array(
            [json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))],
            dtype=f"U{max(1, len(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(',', ':'))))}",
        )
        arrays.update(extra_arrays)
        _update_embedded_labels(arrays, output_path.name, report)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f"{output_path.name}.{os.getpid()}.tmp.npz")
    try:
        np.savez_compressed(tmp_path, **arrays)
        os.replace(tmp_path, output_path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
    report_path = output_path.with_suffix(output_path.suffix + ".basket_subtract.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="Player raw .npz that contains the tag")
    parser.add_argument("basket", help="Player raw .npz with the same basket but no tag")
    parser.add_argument("-o", "--output", help="Output .npz path")
    parser.add_argument("--window", type=int, default=31, help="Odd moving-average window for basket low-pass model")
    parser.add_argument("--match-k", type=int, default=5, help="Number of nearest basket frames to blend")
    parser.add_argument(
        "--channel",
        default="both",
        choices=("both", "upper", "lower"),
        help="Channel to subtract; skipped channels are copied unchanged",
    )
    parser.add_argument(
        "--label-mask",
        default="exact",
        choices=("exact", "span"),
        help="Use exact tag-marked frames or the full min..max tag span for report metrics",
    )
    parser.add_argument("--baseline", type=float, default=BASELINE_DEFAULT, help="ADC value used as zero after subtraction")
    args = parser.parse_args()
    report = run(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
