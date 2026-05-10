#!/usr/bin/env python3
"""
セブンデイズホテル 施設レポート PPTX 生成

Usage:
    python src/create_sevendays_report.py \
        --revpar1 <RevPAR_202412202511.csv> \
        --revpar2 <RevPAR_202505202604.csv> \
        --changes <変動回数.csv> \
        --output  sevendays_report.pptx
"""

import argparse
import csv
import io
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

_JP_FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
if Path(_JP_FONT).exists():
    fm.fontManager.addfont(_JP_FONT)
    plt.rcParams["font.family"] = "IPAGothic"

SLIDE_W = Inches(13.33)
SLIDE_H = Inches(7.5)

COLOR_ACCENT = RGBColor(0x1F, 0x49, 0x7D)
COLOR_LIGHT  = RGBColor(0xD9, 0xE2, 0xF3)
COLOR_WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
COLOR_DARK   = RGBColor(0x40, 0x40, 0x40)
COLOR_GRAY   = RGBColor(0x80, 0x80, 0x80)
COLOR_PLACEHOLDER = RGBColor(0xF2, 0xF2, 0xF2)
COLOR_BORDER = RGBColor(0xBF, 0xBF, 0xBF)

C_2025 = "#4472C4"
C_2026 = "#ED7D31"

FACILITY = "セブンデイズホテル"


# ---------------------------------------------------------------------------
# CSV loaders
# ---------------------------------------------------------------------------

def load_revpar(path):
    rows = []
    with open(path, newline="", encoding="shift_jis", errors="replace") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if not row or not row[0].strip():
                continue
            rows.append({
                "month":  row[0][:7],
                "rooms":  int(row[1]),
                "revenue": int(row[2]),
                "adr":    float(row[3]),
                "occ":    float(row[4]),
                "revpar": float(row[5]),
            })
    return rows


def load_changes(path):
    """
    Wide-format CSV: site, period, day1 … day89
    Returns {year_str: {day_index: total_count_all_channels}}
    Feb=0-27, Mar=28-58, Apr=59-88
    """
    totals = defaultdict(lambda: defaultdict(int))
    with open(path, newline="", encoding="shift_jis", errors="replace") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if not row or not row[0].strip():
                continue
            period = row[1].strip()
            year   = period[:4]
            for i, v in enumerate(row[2:]):
                try:
                    totals[year][i] += int(v.strip())
                except ValueError:
                    pass
    return totals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _header_bar(slide, text):
    bar = slide.shapes.add_shape(1, 0, 0, SLIDE_W, Inches(0.6))
    bar.fill.solid()
    bar.fill.fore_color.rgb = COLOR_ACCENT
    bar.line.fill.background()

    txb = slide.shapes.add_textbox(Inches(0.3), Inches(0.1), Inches(12.7), Inches(0.45))
    p   = txb.text_frame.paragraphs[0]
    run = p.add_run()
    run.text = text
    run.font.size  = Pt(18)
    run.font.bold  = True
    run.font.color.rgb = COLOR_WHITE


def _textbox(slide, text, left, top, width, height,
             size=12, bold=False, color=None, align=PP_ALIGN.LEFT, wrap=False):
    txb = slide.shapes.add_textbox(left, top, width, height)
    tf  = txb.text_frame
    tf.word_wrap = wrap
    p   = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size  = Pt(size)
    run.font.bold  = bold
    run.font.color.rgb = color or COLOR_DARK


def _fig_to_buf(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf


# ---------------------------------------------------------------------------
# Slides
# ---------------------------------------------------------------------------

def slide_cover(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    bar = slide.shapes.add_shape(1, 0, 0, SLIDE_W, Inches(1.6))
    bar.fill.solid()
    bar.fill.fore_color.rgb = COLOR_ACCENT
    bar.line.fill.background()

    _textbox(slide, "施設レポート",
             Inches(0.5), Inches(0.4), Inches(12), Inches(0.85),
             size=28, bold=True, color=COLOR_WHITE)
    _textbox(slide, FACILITY,
             Inches(0.5), Inches(2.0), Inches(12), Inches(1.2),
             size=40, bold=True, color=COLOR_ACCENT)
    _textbox(slide, "2025年2月〜2026年4月",
             Inches(0.5), Inches(3.5), Inches(12), Inches(0.7),
             size=22, color=COLOR_DARK)
    _textbox(slide, "手間いらず自動　本格運用開始：2026年1月〜",
             Inches(0.5), Inches(4.5), Inches(12), Inches(0.6),
             size=15, color=COLOR_GRAY)


def slide_comparison(prs, revpar_all):
    """Grouped bar charts: OCC / ADR / RevPAR for Feb–Apr 2025 vs 2026."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _header_bar(slide, "導入前後比較（2025年 vs 2026年　2〜4月）")

    by_month = {r["month"]: r for r in revpar_all}
    months   = ["2月", "3月", "4月"]
    keys_25  = ["2025-02", "2025-03", "2025-04"]
    keys_26  = ["2026-02", "2026-03", "2026-04"]

    occ_25  = [by_month[k]["occ"]    for k in keys_25]
    adr_25  = [by_month[k]["adr"]    for k in keys_25]
    rev_25  = [by_month[k]["revpar"] for k in keys_25]
    occ_26  = [by_month[k]["occ"]    for k in keys_26]
    adr_26  = [by_month[k]["adr"]    for k in keys_26]
    rev_26  = [by_month[k]["revpar"] for k in keys_26]

    fig, axes = plt.subplots(1, 3, figsize=(12.5, 5.5))
    x = list(range(3))
    w = 0.35

    specs = [
        (axes[0], "OCC（稼働率）",      occ_25, occ_26, True),
        (axes[1], "ADR（平均客室単価）", adr_25, adr_26, False),
        (axes[2], "RevPAR",             rev_25, rev_26, False),
    ]

    for ax, title, v25, v26, is_pct in specs:
        ax.bar([xi - w/2 for xi in x], v25, w, label="2025年", color=C_2025, zorder=3)
        ax.bar([xi + w/2 for xi in x], v26, w, label="2026年", color=C_2026, zorder=3)
        ax.set_xticks(x)
        ax.set_xticklabels(months, fontsize=10)
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.yaxis.grid(True, linestyle="--", alpha=0.5, zorder=0)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.legend(fontsize=9)

        if is_pct:
            ax.set_ylim(0, 100)
            for xi, (y25, y26) in enumerate(zip(v25, v26)):
                ax.text(xi - w/2, y25 + 1.5, f"{y25:.1f}%", ha="center", fontsize=8.5)
                ax.text(xi + w/2, y26 + 1.5, f"{y26:.1f}%", ha="center", fontsize=8.5)
        else:
            ymax = max(max(v25), max(v26)) * 1.22
            ax.set_ylim(0, ymax)
            for xi, (y25, y26) in enumerate(zip(v25, v26)):
                ax.text(xi - w/2, y25 * 1.03, f"{y25:,.0f}", ha="center", fontsize=8)
                ax.text(xi + w/2, y26 * 1.03, f"{y26:,.0f}", ha="center", fontsize=8)

    fig.tight_layout(pad=2.0)
    slide.shapes.add_picture(
        _fig_to_buf(fig), Inches(0.4), Inches(0.75), Inches(12.5), Inches(6.4))


def slide_changes(prs, changes_data):
    """Monthly total change counts (2026) + screenshot placeholder areas."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _header_bar(slide, "変動回数（デイズ S　2026年3月・4月）")

    year = changes_data.get("2026", {})
    # Feb=day0-27, Mar=day28-58, Apr=day59-88
    mar_total = sum(year.get(i, 0) for i in range(28, 59))
    apr_total = sum(year.get(i, 0) for i in range(59, 89))

    fig, ax = plt.subplots(figsize=(4.2, 3.8))
    bars = ax.bar(["3月", "4月"],
                  [mar_total, apr_total],
                  color=C_2026, width=0.5, zorder=3)
    ax.set_title("月別変動回数合計（全OTA・2026年）", fontsize=10, fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", alpha=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for bar_, total in zip(bars, [mar_total, apr_total]):
        ax.text(bar_.get_x() + bar_.get_width() / 2,
                bar_.get_height() * 1.03,
                f"{total:,}", ha="center", fontsize=12, fontweight="bold")
    fig.tight_layout()
    slide.shapes.add_picture(
        _fig_to_buf(fig), Inches(0.3), Inches(0.8), Inches(4.6), Inches(4.0))

    # ── Screenshot placeholders ──────────────────────────────
    def _placeholder(month_label, top):
        _textbox(slide, f"{month_label}　変動履歴スクリーンショット（デイズ S）",
                 Inches(5.2), top - Inches(0.4), Inches(7.8), Inches(0.38),
                 size=11, bold=True, color=COLOR_ACCENT)
        ph = slide.shapes.add_shape(
            1, Inches(5.2), top, Inches(7.8), Inches(2.75))
        ph.fill.solid()
        ph.fill.fore_color.rgb = COLOR_PLACEHOLDER
        ph.line.color.rgb = COLOR_BORDER
        _textbox(slide, "← ここにスクリーンショットを貼付",
                 Inches(5.2), top + Inches(1.1), Inches(7.8), Inches(0.5),
                 size=11, color=COLOR_GRAY, align=PP_ALIGN.CENTER)

    _placeholder("3月", Inches(1.05))
    _placeholder("4月", Inches(4.2))


def slide_summary(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _header_bar(slide, "まとめ・所感")

    sections = [
        ("OCC / ADR / RevPAR",  ["・", "・"]),
        ("変動回数",             ["・", "・"]),
        ("手間いらず自動 導入効果", ["・", "・"]),
    ]

    y = Inches(0.82)
    for heading, bullets in sections:
        _textbox(slide, f"【{heading}】",
                 Inches(0.8), y, Inches(11.5), Inches(0.42),
                 size=14, bold=True, color=COLOR_ACCENT, wrap=True)
        y += Inches(0.44)
        for bullet in bullets:
            _textbox(slide, bullet,
                     Inches(1.0), y, Inches(11.3), Inches(0.42),
                     size=13, color=COLOR_DARK, wrap=True)
            y += Inches(0.44)
        y += Inches(0.1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="セブンデイズホテル レポート PPTX 生成")
    parser.add_argument("--revpar1", required=True,
                        help="RevPAR CSV（2024-12〜2025-11）")
    parser.add_argument("--revpar2", required=True,
                        help="RevPAR CSV（2025-05〜2026-04）")
    parser.add_argument("--changes", required=True,
                        help="変動回数 CSV（2025/2026 Feb-Apr）")
    parser.add_argument("--output", default="sevendays_report.pptx")
    args = parser.parse_args()

    # Merge RevPAR, deduplicate by month (later file wins)
    revpar_all = load_revpar(args.revpar1) + load_revpar(args.revpar2)
    seen = {}
    for r in revpar_all:
        seen[r["month"]] = r
    revpar_all = sorted(seen.values(), key=lambda r: r["month"])

    changes_data = load_changes(args.changes)

    prs = Presentation()
    prs.slide_width  = SLIDE_W
    prs.slide_height = SLIDE_H

    slide_cover(prs)
    slide_comparison(prs, revpar_all)
    slide_changes(prs, changes_data)
    slide_summary(prs)

    prs.save(args.output)
    print(f"保存しました: {args.output}")


if __name__ == "__main__":
    main()
