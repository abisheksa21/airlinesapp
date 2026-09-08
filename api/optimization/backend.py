"""
Solver-agnostic MILP formulation + backend abstraction.

The mathematical formulation (variables, constraints, objective) is built
once, independent of which solver actually runs it -- see
api/optimization/departure_bank.py and api/optimization/network_protection.py
for the formulations themselves. This module only concerns itself with
"given these arrays, solve the MILP and hand back a solution."

PublicBackend (HiGHS via scipy.optimize.milp) is what the deployed public
application would use -- genuinely tested in this environment, real solves
verified against known-answer toy problems before being trusted here.

GurobiBackend is written against Gurobi's real Python API for local/
research use with a personal academic license, but is NOT installed or
executable in this development environment -- it has not been run here.
Do not treat it as validated the way PublicBackend is; it's provided so the
formulation layer stays genuinely solver-agnostic per the architecture
requirement, not because it's been proven to work.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from typing import Protocol, Union

import numpy as np
import scipy.sparse


@dataclass
class MilpFormulation:
    c: np.ndarray           # objective coefficients, shape (n_vars,)
    A: Union[np.ndarray, scipy.sparse.spmatrix]  # constraint matrix, shape (n_constraints, n_vars) -- sparse for large instances
    lb: np.ndarray          # constraint row lower bounds, shape (n_constraints,)
    ub: np.ndarray          # constraint row upper bounds, shape (n_constraints,)
    integrality: np.ndarray  # 1 = integer/binary, 0 = continuous, shape (n_vars,)
    var_lb: np.ndarray      # variable lower bounds, shape (n_vars,)
    var_ub: np.ndarray      # variable upper bounds, shape (n_vars,)


@dataclass
class MilpSolution:
    success: bool
    status: str  # "optimal" | "infeasible" | "time_limit" | "error"
    x: np.ndarray | None
    objective: float
    solve_seconds: float = 0.0
    message: str | None = None


class OptimizationBackend(Protocol):
    def solve(self, formulation: MilpFormulation) -> MilpSolution: ...


class PublicBackend:
    """Open-source HiGHS solver via scipy.optimize.milp. Bounded, interactive
    instance sizes -- this is what a public deployment should use, since it
    needs no license and no external service."""

    def __init__(self, time_limit_seconds: float | None = None):
        configured = os.getenv("AIRLINE_SOLVER_TIME_LIMIT_SECONDS", "30")
        try:
            configured_seconds = float(configured)
        except ValueError:
            configured_seconds = 30.0
        if not math.isfinite(configured_seconds) or configured_seconds <= 0:
            configured_seconds = 30.0
        self.time_limit_seconds = time_limit_seconds if time_limit_seconds is not None else configured_seconds

    def solve(self, formulation: MilpFormulation) -> MilpSolution:
        import time
        from scipy.optimize import milp, LinearConstraint, Bounds

        start = time.monotonic()
        constraints = LinearConstraint(formulation.A, formulation.lb, formulation.ub)
        bounds = Bounds(formulation.var_lb, formulation.var_ub)
        try:
            options = {}
            if self.time_limit_seconds > 0:
                options["time_limit"] = self.time_limit_seconds
            res = milp(
                c=formulation.c,
                constraints=constraints,
                integrality=formulation.integrality,
                bounds=bounds,
                options=options,
            )
        except Exception as exc:
            return MilpSolution(success=False, status="error", x=None, objective=0.0, message=str(exc))
        elapsed = time.monotonic() - start
        if not res.success:
            status = "time_limit" if getattr(res, "status", None) == 1 else "infeasible"
            return MilpSolution(success=False, status=status, x=None, objective=0.0, solve_seconds=elapsed, message=getattr(res, "message", None))
        return MilpSolution(success=True, status="optimal", x=res.x, objective=float(res.fun), solve_seconds=elapsed, message=getattr(res, "message", None))


class GurobiBackend:
    """Research-grade solver for local/full-scale use with a personal
    academic Gurobi license. NOT installed in this environment -- written
    against Gurobi's real Python API, never executed here. Importing
    gurobipy will raise ImportError if it isn't installed wherever this
    actually runs; that's intentional, not a bug -- this backend should
    only ever be selected explicitly, never as a silent fallback."""

    def solve(self, formulation: MilpFormulation) -> MilpSolution:
        import time
        import gurobipy as gp
        from gurobipy import GRB

        start = time.monotonic()
        model = gp.Model()
        model.setParam("OutputFlag", 0)
        n = len(formulation.c)
        x = {}
        for i in range(n):
            vtype = GRB.BINARY if formulation.integrality[i] else GRB.CONTINUOUS
            lb = 0.0 if vtype == GRB.BINARY else formulation.var_lb[i]
            ub = 1.0 if vtype == GRB.BINARY else formulation.var_ub[i]
            x[i] = model.addVar(lb=lb, ub=ub, vtype=vtype)
        model.setObjective(gp.quicksum(formulation.c[i] * x[i] for i in range(n)), GRB.MINIMIZE)
        for row in range(formulation.A.shape[0]):
            expr = gp.quicksum(
                formulation.A[row, i] * x[i] for i in range(n) if formulation.A[row, i] != 0
            )
            lb, ub = formulation.lb[row], formulation.ub[row]
            if lb == ub:
                model.addConstr(expr == lb)
            else:
                if lb > -float("inf"):
                    model.addConstr(expr >= lb)
                if ub < float("inf"):
                    model.addConstr(expr <= ub)
        model.optimize()
        elapsed = time.monotonic() - start
        if model.status == GRB.OPTIMAL:
            return MilpSolution(
                success=True, status="optimal",
                x=np.array([x[i].X for i in range(n)]), objective=model.ObjVal, solve_seconds=elapsed,
            )
        return MilpSolution(success=False, status="infeasible", x=None, objective=0.0, solve_seconds=elapsed)
