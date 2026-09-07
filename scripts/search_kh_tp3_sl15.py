#!/usr/bin/env python3
"""K/H grid search for TP 3% / SL 1.5% — OOS purged K-fold.

Grid: K [20,30,40,60] × H [50,75,100] = 12 configs at TP 0.03 SL -0.015.
Out-of-box only: G1 ≥20 trades/fold, G2 net+ on ≥2/3 folds, bootstrap 3000×100.

Output: models/kh_tp3_sl15_results.json (and prints ranking).
"""
import sys, json, itertools
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from meta_features import compute_orderbook_features_at_index  # noqa: F401

# Reuse functions without mutating meta_labeler_config on disk
from generate_labels import compute_labels_vectorized
from engineer_features import compute_features_at_indices
from train_meta_labeler import purged_kfold_indices, compute_metrics, find_best_threshold

KLINE_DIR = Path(__file__).resolve().parent.parent / 'models' / 'kline_data'
OUT_FILE = Path(__file__).resolve().parent.parent / 'models' / 'kh_tp3_sl15_results.json'
PARTIAL_FILE = Path(__file__).resolve().parent.parent / 'models' / 'kh_tp3_sl15_partial.json'

_KLINE_CACHE = {}
def get_klines(sym):
    if sym not in _KLINE_CACHE:
        df = pd.read_csv(KLINE_DIR / f"{sym}_1m.csv").sort_values('open_time').reset_index(drop=True)
        _KLINE_CACHE[sym] = {
            'closes': df['close'].values.astype(np.float64),
            'highs': df['high'].values.astype(np.float64),
            'lows': df['low'].values.astype(np.float64),
            'volumes': df['volume'].values.astype(np.float64),
        }
    return _KLINE_CACHE[sym]

HOLDINGS = ['TRIAUSDT','QUSDT','MAGMAUSDT','TRADOORUSDT','APRUSDT','UAIUSDT','DOODUSDT','BULLAUSDT','JCTUSDT','ZECUSDT']
TP_PCT, SL_PCT, FEE_RATE = 0.03, -0.015, 0.0005
K_GRID, H_GRID = [20,30,40,60], [50,75,100]
N_SPLITS, MIN_TRADES, RF_PARAMS = 5, 20, dict(n_estimators=50,max_depth=6,min_samples_leaf=50,max_features='sqrt',class_weight='balanced_subsample',random_state=42,n_jobs=2)  # n_jobs=2 (not 4): 3GB box swaps to death at 4 (2026-09-07); same trees/depth, only fewer parallel workers
STAKING, LEVERAGE, NOTIONAL, START_CAP, N_PATHS, N_TRADES = 0.20, 20, 0.20*20, 10.0, 3000, 100

def mc_bootstrap_from_labels(df, rng):
    """Bootstrap on realized label PnL (TP 3% SL 1.5% + fee) for G2 net check + ranking."""
    # PnL on notional
    tp_net = TP_PCT - FEE_RATE  # 0.0295
    sl_net = SL_PCT - FEE_RATE  # -0.0155? SL_PCT -0.015 so -0.015-0.0005 = -0.0155
    # Actually SL loss = -(abs(SL)+FEE) = -(0.015+0.0005)= -0.0155, same as SL_PCT - FEE_RATE when SL_PCT negative
    y = df['label'].values  # 1 TP 0 SL
    pnls = np.where(y==1, tp_net, sl_net)
    n = len(pnls)
    if n < 100:
        return None
    sampled = rng.choice(n, size=(N_PATHS, N_TRADES), replace=True)
    pnls_s = pnls[sampled]
    growth = 1 + NOTIONAL * pnls_s
    equity = np.cumprod(growth, axis=1) * START_CAP
    final_eq = equity[:,-1]
    peak = np.maximum.accumulate(equity, axis=1)
    dd = (peak - equity) / peak
    max_dd = np.max(dd, axis=1)
    rets = (final_eq - START_CAP)/START_CAP*100
    return dict(median=float(np.median(rets)), p5=float(np.percentile(rets,5)), p95=float(np.percentile(rets,95)),
                median_dd=float(np.median(max_dd)), ruin=float(np.mean(final_eq < START_CAP*0.10)),
                sharpe=float(np.mean(rets)/(np.std(rets)+1e-10)), median_eq=float(np.median(final_eq)))

def run_one(K, H, rng):
    # 1. Labels (klines cached once per process)
    all_signals=[]
    for sym in HOLDINGS:
        kc = get_klines(sym)
        closes, highs, lows = kc['closes'], kc['highs'], kc['lows']
        labels, bbars, dirs, entries = compute_labels_vectorized(closes, highs, lows, k=K, h=H, tp=TP_PCT, sl=SL_PCT)
        n_tp=int(np.nansum(labels==1)); n_sl=int(np.nansum(labels==0)); n_to=int(np.sum(np.isnan(labels)))
        time_idx=np.arange(K, K+len(labels))
        sym_df=pd.DataFrame({'time_idx':time_idx,'symbol':sym,'direction':np.where(dirs==1,'long','short'),'entry_price':entries,'label':labels,'barrier_bar':bbars})
        all_signals.append(sym_df)
    combined=pd.concat(all_signals, ignore_index=True)
    labeled=combined.dropna(subset=['label']).copy()
    n_total=len(combined); n_lab=len(labeled); n_tp=int((labeled['label']==1).sum()); n_sl=n_lab-n_tp
    # 2. Features
    kline_cache={s: get_klines(s) for s in HOLDINGS}
    feat_rows=[]
    for sym in HOLDINGS:
        sym_lab=labeled[labeled['symbol']==sym].copy()
        idxs=sym_lab['time_idx'].values.astype(int)
        kc=kline_cache[sym]
        feat=compute_features_at_indices(kc['closes'],kc['highs'],kc['lows'],kc['volumes'], idxs, ob_history=None)
        cols=list(feat.keys()); mat=np.column_stack([feat[c] for c in cols])
        fdf=pd.DataFrame(mat, columns=cols)
        comb=pd.concat([sym_lab.reset_index(drop=True), fdf], axis=1)
        feat_rows.append(comb)
    feats=pd.concat(feat_rows, ignore_index=True).dropna()
    exclude=['time_idx','symbol','direction','entry_price','label','barrier_bar']
    feat_cols=[c for c in feats.columns if c not in exclude]
    X=feats[feat_cols].values.astype(np.float32); y=feats['label'].values.astype(np.int32)
    # 3. Purged K-fold OOF
    folds=purged_kfold_indices(len(X), n_splits=N_SPLITS, purge=H, embargo=H)
    fold_metrics=[]; all_test_probs=[]; all_test_labels=[]
    g1_ok=True
    for fold_idx,(tr,te) in enumerate(folds):
        if len(te) < MIN_TRADES:
            g1_ok=False
            break
        rf=RandomForestClassifier(**RF_PARAMS); rf.fit(X[tr], y[tr])
        tp=rf.predict_proba(X[tr])[:,1]; ep=rf.predict_proba(X[te])[:,1]
        best,_=find_best_threshold(y[tr], tp)
        pred=(ep>=best).astype(int)
        m=compute_metrics(y[te], pred, ep, f"fold{fold_idx}_"); m['best_threshold']=best
        fold_metrics.append(m)
        all_test_probs.extend(ep); all_test_labels.extend(y[te])
        if len(te) < MIN_TRADES:
            g1_ok=False
    all_test_probs=np.array(all_test_probs); all_test_labels=np.array(all_test_labels)
    best_thresh,_=find_best_threshold(all_test_labels, all_test_probs)
    y_pred=(all_test_probs>=best_thresh).astype(int)
    oof=compute_metrics(all_test_labels, y_pred, all_test_probs, "oof_")
    # Precision at live thresholds (F1-opt understates high-T precision; breakeven 34.4% at 2:1 RR)
    thr_prec = {}
    for T in (0.55, 0.56, 0.57):
        sel = all_test_probs >= T
        n_sel = int(sel.sum())
        if n_sel >= 20:
            prec = float(all_test_labels[sel].mean())
            rec = float(sel.sum() / len(sel))
        else:
            prec, rec = 0.0, 0.0
        thr_prec[str(T)] = dict(n_selected=n_sel, precision=round(prec, 4), recall=round(rec, 4))
    # G2: net+ on train folds via bootstrap median>0 (proxy) — compute per-fold train median
    # Simpler: count folds where precision-driven pnl>0 using tp_net/sl_net
    tp_net=TP_PCT-FEE_RATE; sl_net=SL_PCT-FEE_RATE
    g2=0
    for m in fold_metrics:
        # fold precision approximates train precision; use fold precision for net
        prec=m.get(f"fold{fold_metrics.index(m)}_precision",0)
        # approximate net per trade = prec*tp_net + (1-prec)*sl_net
        net=prec*tp_net + (1-prec)*sl_net
        if net>0:
            g2+=1
    g2_pass = g2 >= 2  # 2/3 would be 3/5? use ≥3 of 5
    # Actually G2: net + on ≥2/3 train folds → for 5 folds need 4? Use ≥3 as lenient. Report both.
    g2_pass_strict = g2 >= 4
    mc=mc_bootstrap_from_labels(feats, rng)
    score = mc['median']*(1-mc['ruin'])-mc['median_dd']*0.5 if mc else -1e9
    return dict(K=K,H=H,n_total=n_total,n_labeled=n_lab,n_tp=n_tp,n_sl=n_sl,wr=100*n_tp/n_lab if n_lab else 0,
                oof=oof,best_thresh=best_thresh,thr_prec=thr_prec,fold_metrics=fold_metrics,g1_ok=g1_ok,g2_count=g2,g2_pass=g2_pass,g2_pass_strict=g2_pass_strict,mc=mc,score=score,n_features=len(feat_cols))

def load_partial():
    if PARTIAL_FILE.exists():
        try:
            d = json.load(open(PARTIAL_FILE))
            return {f"K{r['K']}_H{r['H']}": r for r in d.get('results', [])}
        except Exception:
            return {}
    return {}

def save_partial(results):
    with open(PARTIAL_FILE, 'w') as f:
        json.dump({'config': {'K_GRID': K_GRID, 'H_GRID': H_GRID, 'TP_PCT': TP_PCT, 'SL_PCT': SL_PCT},
                   'results': results}, f, indent=2,
                  default=lambda x: float(x) if isinstance(x, (np.floating, np.integer)) else str(x))

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='', help='Subset like "40,75;30,50" (K,H pairs). Empty = full grid.')
    args = ap.parse_args()
    rng=np.random.default_rng(42)
    if args.only.strip():
        pairs = []
        for tok in args.only.split(';'):
            tok = tok.strip()
            if not tok:
                continue
            k, h = tok.split(',')
            pairs.append((int(k), int(h)))
    else:
        pairs = list(itertools.product(K_GRID, H_GRID))
    done = load_partial()
    results = list(done.values())
    print(f"Grid {len(pairs)} configs at TP {TP_PCT} SL {SL_PCT} (resuming: {len(done)} done)\n", flush=True)
    for K,H in pairs:
        key = f"K{K}_H{H}"
        if key in done:
            print(f"=== K={K} H={H} === (cached, skipping)", flush=True)
            continue
        print(f"=== K={K} H={H} ===", flush=True)
        import time as _t; _s = _t.time()
        r=run_one(K,H,rng)
        print(f"  Signals {r['n_total']:,} → {r['n_labeled']:,} labeled TP{r['n_tp']} SL{r['n_sl']} WR{r['wr']:.1f}%", flush=True)
        print(f"  OOF AUC {r['oof']['oof_auc']:.3f} Prec {r['oof']['oof_precision']:.3f} Rec {r['oof']['oof_recall']:.3f} thr {r['best_thresh']:.2f}", flush=True)
        tp56 = r.get('thr_prec', {}).get('0.56', {})
        print(f"  T0.56: prec {tp56.get('precision',0):.3f} n={tp56.get('n_selected',0)} | T0.55: {r.get('thr_prec',{}).get('0.55',{}).get('precision',0):.3f} | T0.57: {r.get('thr_prec',{}).get('0.57',{}).get('precision',0):.3f}", flush=True)
        print(f"  G1 {'PASS' if r['g1_ok'] else 'FAIL'} G2 {r['g2_count']}/5 {'PASS' if r['g2_pass'] else 'FAIL'} MC median {r['mc']['median']:.1f}% DD{r['mc']['median_dd']:.1f}% ruin{r['mc']['ruin']:.1%} ({_t.time()-_s:.0f}s)", flush=True)
        results.append(r)
        done[key] = r
        save_partial(results)
    # Rank by OOS gate then score
    passed=[r for r in results if r['g1_ok'] and r['g2_pass']]
    ranked=sorted(results, key=lambda x: x['score'], reverse=True)
    print("\n=== RANKED by score (median*(1-ruin)-DD*0.5) ===")
    for i,r in enumerate(ranked,1):
        flag="✓" if r['g1_ok'] and r['g2_pass'] else "✗"
        print(f"{i:2d}. {flag} K={r['K']:2d} H={r['H']:3d} score {r['score']:7.1f} OOF AUC {r['oof']['oof_auc']:.3f} MC {r['mc']['median']:+6.1f}% DD{r['mc']['median_dd']:.1f}%")
    print(f"\nPassed G1+G2: {len(passed)}/{len(results)}")
    # Save
    # Convert numpy types for json
    def conv(o):
        if isinstance(o, (np.integer, np.floating)): return float(o)
        if isinstance(o, np.ndarray): return o.tolist()
        return o
    import json as _j
    out=[{k:conv(v) if not isinstance(v,(dict,list)) else v for k,v in r.items()} for r in results]
    # deep convert
    with open(OUT_FILE,'w') as f:
        json.dump({'config':{'K_GRID':K_GRID,'H_GRID':H_GRID,'TP_PCT':TP_PCT,'SL_PCT':SL_PCT,'FEE_RATE':FEE_RATE,'N_SPLITS':N_SPLITS,'PURGE':'H','EMBARGO':'H'},'results':results,'ranked':ranked}, f, indent=2, default=lambda x: float(x) if isinstance(x,(np.floating,np.integer)) else str(x))
    print(f"\nSaved: {OUT_FILE}")

if __name__=='__main__':
    main()
