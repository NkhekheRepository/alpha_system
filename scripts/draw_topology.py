#!/usr/bin/env python3
"""Render the unified system topology (three strategies + shared components)."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch


def box(ax, x, y, w, h, title, lines, fc):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06",
                 fc=fc, ec='#222', lw=1.4, zorder=3))
    ax.text(x + w/2, y + h - 0.28, title, ha='center', va='center',
            color='white', fontsize=9, fontweight='bold', zorder=4)
    ax.text(x + w/2, y + 0.35, lines, ha='center', va='center',
            color='white', fontsize=7, zorder=4, linespacing=1.4)


def arrow(ax, x1, y1, x2, y2, color='#666'):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle='->',
                  mutation_scale=12, color=color, lw=1.4, zorder=2))


fig, ax = plt.subplots(figsize=(14, 11))
ax.set_xlim(0, 14)
ax.set_ylim(0, 11)
ax.axis('off')

box(ax, 0.3, 8.2, 3.2, 2.3, "ALPHA 1%  (dry_runner.py)",
     "Mainnet PAPER\nUnconditional long churn\n@Nkhekhe_bot", '#3b6ea5')
box(ax, 3.8, 8.2, 3.2, 2.3, "ALPHA 2%  (bidir_runner.py)",
     "Mainnet PAPER\nMomentum K=10 bidir\n@LetapataBot (legacy)", '#6a4ca5')
box(ax, 7.3, 8.2, 3.2, 2.3, "ALPHA 3%  (alpha3_dry_runner.py)",
     "Demo-fapi LIVE HEDGE\nMeta-labeler + TB\n@LetapataBot", '#a5642c')
box(ax, 10.8, 8.2, 3.0, 2.3, "TELEGRAM BOTS",
     "tg_bot.py\n@Nkhekhe_bot\ntg_bot_alpha2.py\n@LetapataBot", '#444')

box(ax, 0.3, 5.0, 3.4, 2.0, "SHARED: binance_config.py",
     "ALPHA3_ASSETS (6)\nAPI base / demo keys\nUSE_TESTNET toggle", '#2c7a4a')
box(ax, 3.9, 5.0, 3.4, 2.0, "SHARED: demo_trader.py",
     "market + bracket orders\nset_leverage_all\nsign / round_qty", '#1f6f6f')
box(ax, 7.5, 5.0, 3.4, 2.0, "SHARED: analytics.py",
     "Sharpe / Sortino / Calmar\ndrawdown / VaR-CVaR\nattribution / health", '#7a5ba5')
box(ax, 11.1, 5.0, 2.7, 2.0, "SHARED: notify.py",
     "Telegram alerts\nequity + trade charts", '#444')

box(ax, 3.9, 1.6, 3.4, 1.8, "MODELS: meta_labeler.joblib",
     "RF secondary filter\nOOF AUC 0.625\nthreshold 0.50", '#a5642c')
box(ax, 7.5, 1.6, 3.4, 1.8, "SCRIPTS: meta-labeler pipeline",
     "fetch → label → features\ntrain → validate", '#2c7a4a')
box(ax, 0.3, 1.6, 3.4, 1.8, "BINANCE",
     "Public ticker/price\n(60s polls)\nDemo-fapi hedge", '#3b6ea5')
box(ax, 11.1, 1.6, 2.7, 1.8, "SYSTEMD",
     "alpha3-dry-runner\nalpha3-tg-bot\nRestart=always", '#444')

# Wiring arrows
arrow(ax, 3.5, 9.3, 3.8, 9.3)            # A1 -> A2
arrow(ax, 7.0, 9.3, 7.3, 9.3)            # A2 -> A3
arrow(ax, 10.5, 9.3, 10.8, 9.3)          # A3 -> bots
arrow(ax, 1.9, 8.2, 1.9, 7.0)            # A1 -> config
arrow(ax, 5.5, 8.2, 5.5, 7.0)            # A2 -> demo
arrow(ax, 8.9, 8.2, 8.9, 7.0)            # A3 -> analytics
arrow(ax, 11.0, 8.2, 11.0, 7.0)          # bots -> notify
arrow(ax, 2.0, 5.0, 2.0, 3.4)            # config -> binance
arrow(ax, 5.6, 5.0, 5.6, 3.4)            # demo -> model
arrow(ax, 9.2, 5.0, 9.2, 3.4)            # analytics -> scripts
arrow(ax, 12.0, 5.0, 12.0, 3.4)          # notify -> systemd

ax.set_title("ALPHA SYSTEM — UNIFIED TOPOLOGY\n(Alpha 1 / Alpha 2 / Alpha 3 + shared components)",
             fontsize=13, fontweight='bold', color='#222', pad=12)

fig.savefig('docs/images/topology.png', dpi=150, bbox_inches='tight', facecolor='white')
print("wrote docs/images/topology.png")
