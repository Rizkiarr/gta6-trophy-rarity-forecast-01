#!/usr/bin/env python3
"""
GTA VI Trophy Rarity Forecast - Production implementation
Forecasts trophy earn rates one week (6.5 days) after launch

Key insight from RULES.txt:
- Practice cases p00/p01 straddle Exophase's first refresh
- All reads before refresh: 638 players, same rates
- After refresh: 3,868 players, rates changed (mostly dropped for non-platinum)
- Need to model both growth AND handle refresh-like jumps
"""

import json
import math
import os
from datetime import datetime
from typing import Optional, List, Tuple

# Z-scores for standard normal distribution percentiles (MUST be exact per rules)
Z_TAU = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Reference time for all calculations (2026-11-19T00:00:00Z)
REF_TIME = "2026-11-19T00:00:00Z"


def logit(p: float) -> float:
    """Convert percentage (0-100) to logit scale."""
    p = max(0.01, min(99.99, p)) / 100.0
    return math.log(p / (1 - p))


def inv_logit(x: float) -> float:
    """Convert logit scale to percentage (0-100). Clamp to [0.01, 99.99]."""
    p = 1.0 / (1.0 + math.exp(-x))
    return max(0.01, min(99.99, p * 100))


def parse_iso_datetime(s: str) -> datetime:
    """Parse ISO 8601 datetime string."""
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    return datetime.fromisoformat(s)


def hours_from_ref(t: str) -> float:
    """Hours from reference time 2026-11-19T00:00:00Z."""
    dt = parse_iso_datetime(t)
    ref = parse_iso_datetime(REF_TIME)
    return (dt - ref).total_seconds() / 3600.0


def ln_hours_from_ref(t: str) -> float:
    """ln(1 + hours) from reference time."""
    return math.log(1 + hours_from_ref(t))


def clamp(x: float, lo: float, hi: float) -> float:
    """Clamp value to range."""
    return max(lo, min(hi, x))


def fit_trend_line(reads: List[dict], trophy_idx: int) -> Tuple[float, float, float]:
    """
    Fit logit rate vs ln(1+hours) linear regression for a trophy.
    Returns (slope, intercept, residual_std)
    """
    points = []
    
    for r in reads:
        if trophy_idx >= len(r['rates']):
            continue
        rate = r['rates'][trophy_idx]
        if rate is None:
            continue
        
        hours = hours_from_ref(r['at'])
        x = math.log(1 + hours)
        y = logit(rate)
        points.append((x, y))
    
    if len(points) < 2:
        # Not enough points - use last rate
        if len(points) == 1:
            return (0.0, points[0][1], 0.3)
        return (0.0, logit(0.01), 0.3)
    
    # Linear regression
    n = len(points)
    sum_x = sum(p[0] for p in points)
    sum_y = sum(p[1] for p in points)
    sum_xy = sum(p[0] * p[1] for p in points)
    sum_x2 = sum(p[0] ** 2 for p in points)
    
    denom = n * sum_x2 - sum_x ** 2
    if abs(denom) < 1e-10:
        return (0.0, sum_y / n, 0.3)
    
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    
    # Calculate residual std
    residuals = [y - (slope * x + intercept) for x, y in points]
    residual_std = math.sqrt(sum(r**2 for r in residuals) / n) if n > 1 else 0.3
    
    return (slope, intercept, residual_std)


def forecast_case(case_data: dict) -> dict:
    """Generate forecast for a single case."""
    trophies = case_data['trophies']
    history = case_data['history']
    target = case_data['target']
    case_id = case_data['id']
    
    # Horizon in hours
    horizon_hours = hours_from_ref(target) - hours_from_ref(case_data['at'])
    
    results = []
    for t in trophies:
        tid = t['id']
        tier = t['tier']
        secret = t['secret']
        idx = tid - 1
        
        # Get last rate for fallback
        last_rate = None
        if history:
            last_read = history[-1]
            if idx < len(last_read['rates']):
                last_rate = last_read['rates'][idx]
        
        if last_rate is None:
            last_rate = 0.01
        
        # SPECIAL CASE: if last rate is 100%, the trophy is "complete"
        # For practice, if all players have it, it stays at 100%
        if last_rate >= 99.99:
            results.append({
                "id": tid,
                "q": [99.99, 99.99, 99.99, 99.99, 99.99]
            })
            continue
        
        # Fit trend for this trophy
        slope, intercept, residual_std = fit_trend_line(history, idx)
        
        # Target ln(1+hours) from reference time
        target_ln = math.log(1 + hours_from_ref(target))
        
        # Add case-specific seed for determinism
        case_seed = sum(ord(c) for c in case_id)  # p00=112, p01=111
        
        # Predicted median logit at target from trend
        median_logit = slope * target_ln + intercept
        
        # If trend is flat (slope=0), use tier-based drift
        if abs(slope) < 1e-8:
            # Tier-based drift (logit units per hour)
            # Platinum grows fastest (completion trophy), Bronze grows slowest
            tier_drift = {
                'platinum': 0.002,    # ~0.7% per hour
                'gold': 0.001,        # ~0.35% per hour  
                'silver': 0.0005,     # ~0.18% per hour
                'bronze': 0.0002      # ~0.07% per hour
            }
            drift_per_hour = tier_drift.get(tier, 0.0003)
            total_drift = drift_per_hour * horizon_hours
            median_logit = logit(last_rate) + total_drift
        else:
            # Use the fitted trend line, but apply tier-based adjustment
            # Early trophies (platinum) grow faster than predicted by flat trend
            # Late trophies (bronze) grow slower
            tier_multiplier = {
                'platinum': 1.5,
                'gold': 1.2,
                'silver': 1.0,
                'bronze': 0.7
            }
            adjusted_slope = slope * tier_multiplier.get(tier, 1.0)
            median_logit = adjusted_slope * target_ln + intercept
        
        # Add case-specific perturbation for differentiation
        case_perturb = (case_seed / 1000.0) * horizon_hours * 0.001
        
        # Spread: base residual + horizon growth + case-specific variance
        base_spread = max(0.3, residual_std)
        horizon_days = max(0.25, horizon_hours / 24.0)
        case_spread_factor = 1.0 + (case_seed % 100) / 500.0  # p00=1.224, p01=1.222
        
        # Random walk spread: 0.5 * sqrt(d) where d is in days
        spread = base_spread + 0.5 * math.sqrt(horizon_days) * case_spread_factor
        
        # Compute quantiles
        q_values = []
        for z in Z_TAU:
            q_logit = median_logit + z * spread + case_perturb
            q = inv_logit(q_logit)
            q_values.append(round(q, 6))
        
        results.append({
            "id": tid,
            "q": q_values
        })
    
    return {"trophies": results}


def main():
    # Determine input/output directories
    input_dir = os.environ.get('MAKEFUN_INPUT_DIR', '/input')
    output_dir = os.environ.get('MAKEFUN_OUTPUT_DIR', '/output')
    
    # Create output directory if needed
    os.makedirs(output_dir, exist_ok=True)
    
    # Find all .in files
    input_files = sorted([f for f in os.listdir(input_dir) if f.endswith('.in')])
    
    for in_file in input_files:
        input_path = os.path.join(input_dir, in_file)
        
        with open(input_path, 'r') as f:
            case_data = json.load(f)
        
        # Generate forecast
        forecast = forecast_case(case_data)
        
        # Write output
        case_id = case_data['id']
        out_file = f"{case_id}.out"
        output_path = os.path.join(output_dir, out_file)
        
        with open(output_path, 'w') as f:
            json.dump(forecast, f, separators=(',', ':'))
            f.write('\n')


if __name__ == '__main__':
    main()