#!/usr/bin/env python3
"""Render the Alpha 3 end-to-end pipeline as a PNG flowchart.

Shows how gates accept/reject signals until BUY/SELL, the triple-barrier
exit monitor, and the equity/risk feedback loop. Reproducible:
    python3 scripts/draw_pipeline.py
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.lines import Line2D


def box(ax, x, y, w, h, text, fc, ec='#222', tc='white', fs=9, style='round'):
    ax.add_patch(FancyBboxPatch((x - w/2, y - h/2), w, h,
                 boxstyle=f"round,pad=0.02,rounding_size=0.08" if style == 'round' else "square,pad=0.02",
                 fc=fc, ec=ec, lw=1.4, zorder=3))
    ax.text(x, y, text, ha='center', va='center', color=tc, fontsize=fs,
            zorder=4, wrap=True)


def arrow(ax, x1, y1, x2, y2, color='#888', style='->'):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                  mutation_scale=14, color=color, lw=1.6, zorder=2))


def diamond(ax, x, y, w, h, text, fc, tc='white', fs=8):
    ax.add_patch(plt.Polygon([(x, y+h/2), (x+w/2, y), (x, y-h/2), (x-w/2, y)],
                  fc=fc, ec='#222', lw=1.4, zorder=3))
    ax.text(x, y, text, ha='center', va='center', color=tc, fontsize=fs, zorder=4)


fig, ax = plt.subplots(figsize=(13, 16))
ax.set_xlim(0, 12)
ax.set_ylim(0, 26)
ax.axis('off')

# Colors
C_DATA = '#3b6ea5'
C_SIG = '#6a4ca5'
C_META = '#a5642c'
C_GATE = '#2c7a4a'
C_REJ = '#a52c2c'
C_TRADE = '#1f6f6f'
C_EXIT = '#7a5ba5'
C_FEED = '#444'

# --- Flow (top -> bottom) ---
box(ax, 6, 24.3, 4.6, 1.1, "BINANCE 60s TICKER / KLINES\n(live price feed, no keys)", C_DATA)
box(ax, 6, 22.4, 4.6, 1.0, "OHLCV BOOTSTRAP\n(200 × 1m bars per asset)", C_DATA)
box(ax, 6, 20.5, 4.8, 1.1, "PRIMARY SIGNAL\nmomentum-K10 → dir LONG / SHORT", C_SIG)
box(ax, 6, 18.4, 4.8, 1.2, "META-LABELER\n36 features → RF → P(win)", C_META)
diamond(ax, 6, 15.9, 3.0, 1.8, "P(win)\n≥ 0.50 ?", C_GATE)

# Reject branch (left)
box(ax, 2.2, 15.9, 3.0, 1.1, "META-FILTER\nREJECT → skip,\naudit next cycle", C_REJ)
# Accept branch (right)
box(ax, 9.8, 15.9, 3.0, 1.1, "META-PASS\nACCEPT → ENTER", C_GATE)

box(ax, 9.8, 13.6, 3.4, 1.2, "DEMO MARKET ENTRY\n+ bracket TP/SL orders", C_TRADE)
box(ax, 9.8, 11.4, 4.6, 1.3, "TRIPLE-BARRIER MONITOR\n(every 60s) TP +2% / SL −2% / TIMEOUT H=100", C_EXIT)
diamond(ax, 9.8, 8.9, 3.2, 1.8, "EXIT\nTRIGGERED ?", C_EXIT)
box(ax, 9.8, 6.4, 4.4, 1.2, "REALIZE PnL\nupdate equity + effective_equity", C_TRADE)
box(ax, 9.8, 4.3, 4.6, 1.2, "CIRCUIT BREAKER\n3 consecutive losses → 50-bar cooldown", C_FEED)
box(ax, 6, 2.4, 4.8, 1.2, "EQUITY LOG → ANALYTICS → TELEGRAM\n(@LetapataBot status / charts / risk)", C_SIG)

# --- Arrows ---
arrow(ax, 6, 23.75, 6, 22.9)             # data -> bootstrap
arrow(ax, 6, 21.9, 6, 21.0)              # bootstrap -> signal
arrow(ax, 6, 19.95, 6, 19.0)             # signal -> meta
arrow(ax, 6, 17.8, 6, 16.8)              # meta -> gate
arrow(ax, 4.5, 15.9, 3.7, 15.9, color=C_REJ)   # gate -> reject
arrow(ax, 7.5, 15.9, 8.3, 15.9, color=C_GATE)  # gate -> accept
arrow(ax, 9.8, 15.35, 9.8, 14.2)         # accept -> entry
arrow(ax, 9.8, 13.0, 9.8, 12.05)         # entry -> monitor
arrow(ax, 9.8, 10.75, 9.8, 9.8)          # monitor -> exit diamond
arrow(ax, 9.8, 8.0, 9.8, 7.0)            # exit -> realize
arrow(ax, 9.8, 5.8, 9.8, 4.9)            # realize -> breaker
arrow(ax, 9.8, 3.7, 8.4, 3.0)            # breaker -> telegram
arrow(ax, 7.6, 2.4, 6.8, 2.4)            # telegram -> left
# feedback loop back up to signal
ax.add_patch(FancyArrowPatch((6.8, 2.4), (6, 21.0), connectionstyle="arc3,rad=-0.35",
              arrowstyle='->', mutation_scale=14, color=C_FEED, lw=1.6, ls='--', zorder=2))
ax.text(1.2, 12.0, "FEEDBACK LOOP\n(equity + risk state\nfeeds next cycle)",
         color=C_FEED, fontsize=8, ha='left', va='center')

# Reject re-entry note
ax.add_patch(FancyArrowPatch((2.2, 15.35), (2.2, 3.0), connectionstyle="arc3,rad=0.3",
              arrowstyle='->', mutation_scale=12, color=C_REJ, lw=1.3, ls=':', zorder=2))
ax.text(0.2, 9.0, "filtered signals\nre-evaluated\nnext poll", color=C_REJ, fontsize=7, ha='left')

# Legend
legend = [
    Line2D([0], [0], color=C_DATA, lw=6, label='Data'),
    Line2D([0], [0], color=C_SIG, lw=6, label='Signal / Observability'),
    Line2D([0], [0], color=C_META, lw=6, label='Meta-labeler'),
    Line2D([0], [0], color=C_GATE, lw=6, label='Gate (accept)'),
    Line2D([0], [0], color=C_REJ, lw=6, label='Gate (reject)'),
    Line2D([0], [0], color=C_TRADE, lw=6, label='Trade / Exit'),
    Line2D([0], [0], color=C_FEED, ls='--', lw=4, label='Feedback loop'),
]
ax.legend(handles=legend, loc='upper left', bbox_to_anchor=(0.0, 0.02),
          fontsize=8, framealpha=0.9, ncol=1)

ax.set_title("ALPHA 3 DRY MODE — END-TO-END PIPELINE\nSignal → Meta-Labeler Gate → Buy/Sell → Triple-Barrier → Feedback Loop",
             fontsize=13, fontweight='bold', color='#222', pad=12)

import os
os.makedirs('docs/images', exist_ok=True)
fig.savefig('docs/images/pipeline.png', dpi=150, bbox_inches='tight', facecolor='white')
print("wrote docs/images/pipeline.png")
