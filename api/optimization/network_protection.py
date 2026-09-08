"""
Network Protection Portfolio Optimizer -- OR Feature 2.

Answers: if only a limited number of interventions/resources are available,
where in the airline network should they be allocated?

Formulation (0/1 knapsack MILP):
  Sets:
    J = candidate intervention targets (airports, directional routes, or
        departure banks -- whatever candidate set is passed in)

  Decision variables:
    x_j in {0,1}  -- 1 if candidate j is selected for intervention

  Budget constraint:
    sum_j cost_j * x_j <= Budget

  Objective (maximize):
    sum_j primary_metric_j * x_j

DELIBERATE DESIGN CHOICE, directly required by the spec: this does NOT
combine volume, severe-delay probability, propagation, concentration, route
exposure, cancellation exposure, and congestion pressure into one invented
composite score. The user picks ONE real, disclosed metric to actually
OPTIMIZE against (primary_metric) -- the MILP maximizes exactly that,
nothing hidden. Every OTHER component is still reported for the resulting
portfolio, so the selection's coverage across every dimension is visible,
but none of them silently influenced the decision unless chosen as the
primary metric. This mirrors the same discipline already used in this
project's Decision Center (point_gain and flight_volume shown separately,
never multiplied into a fake priority score).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np

from api.optimization.backend import MilpFormulation, OptimizationBackend, PublicBackend


@dataclass
class InterventionCandidate:
    candidate_id: str
    candidate_type: str  # "airport" | "route" | "departure_bank"
    cost: float
    components: dict[str, float]  # e.g. {"volume": ..., "severe_delay_rate": ..., "propagation_score": ..., "cancellation_rate": ..., "congestion_pressure": ...}


@dataclass
class PortfolioResult:
    status: str
    primary_metric: str
    budget: float
    selected: list[dict]
    rejected: list[dict]
    resource_consumed: float
    total_coverage: dict[str, float]  # sum of EVERY component across the selected portfolio, not just primary_metric
    residual_exposure: dict[str, float]  # sum of every component across candidates NOT selected
    methodology: dict


def _solve_selection(
    candidates: list[InterventionCandidate],
    budget: float,
    primary_metric: str,
    backend: OptimizationBackend,
) -> tuple[str, list[int], list[int]]:
    """Just the knapsack MILP solve -- returns (status, selected_idx,
    rejected_idx), no marginal-gain computation. This is the piece
    _compute_marginal_gains must call recursively, NOT solve_portfolio:
    solve_portfolio always computes marginal gains for its own selection,
    so recursing into it turns one "remove a candidate and re-solve" check
    into an exponential fan-out (each re-solve triggers its own marginal-gain
    re-solves, which trigger theirs, ...). With budget=3 across 11
    candidates that blew up to 4,000+ nested MILP calls within 25s and
    climbing (verified before this fix) -- not a slow solve, an accidental
    exponential recursion misidentified as one."""
    n = len(candidates)
    c = np.array([-cand.components.get(primary_metric, 0.0) for cand in candidates])  # minimize -value == maximize value
    A = np.array([[cand.cost for cand in candidates]])
    lb = np.array([-np.inf])
    ub = np.array([budget])
    integrality = np.ones(n)
    var_lb = np.zeros(n)
    var_ub = np.ones(n)

    formulation = MilpFormulation(c=c, A=A, lb=lb, ub=ub, integrality=integrality, var_lb=var_lb, var_ub=var_ub)
    solution = backend.solve(formulation)
    if not solution.success:
        return solution.status, [], []

    x = solution.x
    selected_idx = [i for i in range(n) if x[i] > 0.5]
    rejected_idx = [i for i in range(n) if x[i] <= 0.5]
    return solution.status, selected_idx, rejected_idx


def solve_portfolio(
    candidates: list[InterventionCandidate],
    budget: float,
    primary_metric: str,
    backend: OptimizationBackend | None = None,
) -> PortfolioResult:
    backend = backend or PublicBackend()

    if not math.isfinite(budget) or budget < 0:
        raise ValueError("budget must be a finite non-negative number")
    for candidate in candidates:
        if not math.isfinite(candidate.cost) or candidate.cost <= 0:
            raise ValueError(f"candidate {candidate.candidate_id} must have a finite positive cost")
    if candidates and any(primary_metric not in candidate.components for candidate in candidates):
        raise ValueError(f"primary_metric '{primary_metric}' is missing from one or more candidates")

    if not candidates:
        return PortfolioResult(
            status="no_candidates", primary_metric=primary_metric, budget=budget,
            selected=[], rejected=[], resource_consumed=0.0, total_coverage={}, residual_exposure={},
            methodology=_methodology(primary_metric),
        )

    solve_status, selected_idx, rejected_idx = _solve_selection(candidates, budget, primary_metric, backend)

    if solve_status != "optimal":
        result_status = solve_status if solve_status in {"time_limit", "error"} else "infeasible"
        return PortfolioResult(
            status=result_status, primary_metric=primary_metric, budget=budget,
            selected=[], rejected=[{"candidate_id": c.candidate_id, "reason": "solve failed"} for c in candidates],
            resource_consumed=0.0, total_coverage={}, residual_exposure={}, methodology=_methodology(primary_metric),
        )

    marginal_gains = _compute_marginal_gains(candidates, budget, primary_metric, selected_idx, backend)

    selected = []
    for i in selected_idx:
        cand = candidates[i]
        selected.append({
            "candidate_id": cand.candidate_id,
            "candidate_type": cand.candidate_type,
            "cost": cand.cost,
            "components": cand.components,
            "marginal_gain": marginal_gains.get(cand.candidate_id, 0.0),
            "reason": f"Selected -- contributes {cand.components.get(primary_metric, 0.0):.3g} of chosen metric '{primary_metric}' at cost {cand.cost}.",
        })

    rejected = []
    for i in rejected_idx:
        cand = candidates[i]
        rejected.append({
            "candidate_id": cand.candidate_id,
            "candidate_type": cand.candidate_type,
            "cost": cand.cost,
            "components": cand.components,
            "reason": _rejection_reason(cand, budget, primary_metric, selected, rejected_idx, candidates),
        })

    total_coverage = _sum_components([candidates[i] for i in selected_idx])
    residual_exposure = _sum_components([candidates[i] for i in rejected_idx])
    resource_consumed = sum(candidates[i].cost for i in selected_idx)

    return PortfolioResult(
        status="optimal",
        primary_metric=primary_metric,
        budget=budget,
        selected=selected,
        rejected=rejected,
        resource_consumed=round(resource_consumed, 3),
        total_coverage={k: round(v, 3) for k, v in total_coverage.items()},
        residual_exposure={k: round(v, 3) for k, v in residual_exposure.items()},
        methodology=_methodology(primary_metric),
    )


def _compute_marginal_gains(candidates, budget, primary_metric, selected_idx, backend) -> dict[str, float]:
    """For each SELECTED candidate, marginal_gain = how much the portfolio's
    total primary-metric coverage would DROP if that one candidate were
    forced out and the rest re-optimized under the same budget. A real,
    computed sensitivity measure -- not an approximation."""
    base_total = sum(candidates[i].components.get(primary_metric, 0.0) for i in selected_idx)
    gains = {}
    for i in selected_idx:
        remaining = [c for j, c in enumerate(candidates) if j != i]
        if not remaining:
            gains[candidates[i].candidate_id] = base_total
            continue
        sub_status, sub_selected_idx, _ = _solve_selection(remaining, budget, primary_metric, backend)
        sub_total = (
            sum(remaining[j].components.get(primary_metric, 0.0) for j in sub_selected_idx)
            if sub_status == "optimal" else 0.0
        )
        gains[candidates[i].candidate_id] = round(base_total - sub_total, 4)
    return gains


def _rejection_reason(cand, budget, primary_metric, selected, rejected_idx, candidates) -> str:
    if cand.cost > budget:
        return f"Cost {cand.cost} exceeds the entire budget {budget} on its own."
    return (
        f"Not selected -- {cand.components.get(primary_metric, 0.0):.3g} of '{primary_metric}' at cost "
        f"{cand.cost} was outcompeted by higher-value-per-cost alternatives within the {budget} budget."
    )


def _sum_components(candidates: list[InterventionCandidate]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for cand in candidates:
        for key, val in cand.components.items():
            totals[key] = totals.get(key, 0.0) + val
    return totals


def _methodology(primary_metric: str) -> dict:
    return {
        "framework": "0/1 knapsack MILP, solved via an open-source HiGHS backend for public/bounded instances.",
        "primary_metric": primary_metric,
        "cost_policy": (
            "Costs are explicit candidate inputs. The API can use equal-unit cost, "
            "flight-volume exposure, or a square-root volume proxy; none should be "
            "read as dollars until airline-specific intervention-cost data is supplied."
        ),
        "combination_policy": (
            "The optimizer maximizes ONLY the chosen primary_metric -- volume, severe-delay rate, "
            "propagation, cancellation exposure, and congestion pressure are never combined into an "
            "unexplained composite score. Every component is still reported for the resulting "
            "portfolio so its coverage across every dimension is visible, not just the one optimized."
        ),
        "marginal_gain_method": "Computed by re-solving the portfolio with each selected candidate forced out, one at a time -- a real, exact sensitivity measure, not an approximation.",
        "limitations": [
            "This is a resource-allocation optimizer over DISCLOSED historical metrics, not a causal claim that intervening at a selected target will produce a specific improvement.",
            "Costs are user-supplied inputs (e.g. staffing/attention budget) -- this project does not have real intervention-cost data.",
        ],
    }
