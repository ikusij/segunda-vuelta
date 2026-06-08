import csv
import json
import os
from datetime import datetime

from monte_carlo import (
    MonteCarloConfig,
    aggregate_province,
    make_synthetic_result,
    monte_carlo_simulation
)

TIMESERIES_FILE = "timeseries.csv"
TIMESERIES_COLUMNS = ["timestamp", "pct_counted", "candidate", "projected_votes", "votes_counted"]

def run_national_simulation(
    bundle_path: str = "bundle.json",
    n_simulations: int = 1_000,
    prior: str | float = "flat",
    confidence_level: float = 0.95,
    random_seed: int | None = None,
    votes_per_acta: int = 220,
    timestamp: datetime | None = None,
    save_timeseries: bool = True,
):
    config = MonteCarloConfig(
        n_simulations=n_simulations,
        prior=prior,
        confidence_level=confidence_level,
        random_seed=random_seed,
    )

    print(f"Loading {bundle_path}...")
    with open(bundle_path, encoding="utf-8") as f:
        bundle = json.load(f)

    print(f"Running simulation over {len(bundle)} districts ({n_simulations:,} simulations each)...")

    district_data = list(bundle.values())
    results = []
    for i, data in enumerate(district_data, 1):
        results.append(monte_carlo_simulation(data, config))
        if i % 200 == 0 or i == len(district_data):
            skipped = sum(1 for r in results if r is None)
            print(f"  {i}/{len(district_data)} districts processed ({skipped} skipped so far)...")

    # Build province/department aggregates to back-fill skipped districts
    province_valid: dict[str, list] = {}
    department_valid: dict[str, list] = {}
    for data, result in zip(district_data, results):
        if result is None:
            continue
        uid = str(data["ubigeo_distrito"])
        province_valid.setdefault(uid[:4], []).append(result)
        department_valid.setdefault(uid[:2], []).append(result)

    province_aggregates = {pc: aggregate_province(rs) for pc, rs in province_valid.items()}
    department_aggregates = {dc: aggregate_province(rs) for dc, rs in department_valid.items()}

    # Synthesise skipped districts using provincial/departmental distribution
    synthetic_results = []
    for data, result in zip(district_data, results):
        if result is not None:
            continue
        uid = str(data["ubigeo_distrito"])
        fallback = province_aggregates.get(uid[:4]) or department_aggregates.get(uid[:2])
        total_votes = data.get("pendientesJee", 0) * votes_per_acta
        synthetic = make_synthetic_result(fallback, total_votes)
        if synthetic is not None:
            synthetic_results.append(synthetic)

    all_results = [r for r in results if r is not None] + synthetic_results
    print(f"\nAggregating {len(all_results)} results ({len(synthetic_results)} synthetic)...")
    national = aggregate_province(all_results)

    if timestamp and save_timeseries:
        ts_str = timestamp.strftime("%Y-%m-%d %H:%M")
        write_header = not os.path.exists(TIMESERIES_FILE)
        with open(TIMESERIES_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=TIMESERIES_COLUMNS)
            if write_header:
                writer.writeheader()
            for c in national.candidates:
                writer.writerow({
                    "timestamp":       ts_str,
                    "pct_counted":     round(national.pct_counted, 6),
                    "candidate":       c.name,
                    "projected_votes": int(c.projected_share * national.total_votes),
                    "votes_counted":   c.votes_counted,
                })
        print(f"\nSaved snapshot '{ts_str}' → {TIMESERIES_FILE}")

    # Always order so that KEIKO goes first, then SANCHEZ, then others.
    def candidate_priority(c):
        name = c.name.upper()
        if "KEIKO" in name:
            return 0
        if "SANCHEZ" in name:
            return 1
        return 2

    # Get top 2: KEIKO, SANCHEZ, then others by projected votes. Flatten [projected_votes, votes_counted] for each.
    return [
        item
        for c in sorted(
            national.candidates,
            key=lambda c: (candidate_priority(c), -(c.projected_share * national.total_votes))
        )[:2]
        for item in (int(c.projected_share * national.total_votes), c.votes_counted)
    ]

if __name__ == "__main__":
    print(run_national_simulation(timestamp=datetime.strptime("2026-05-07 20:00", "%Y-%m-%d %H:%M")))