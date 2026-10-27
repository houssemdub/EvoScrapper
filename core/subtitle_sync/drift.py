"""
core/subtitle_sync/drift.py — Framerate and Non-Linear Drift Modeling.
Calculates linear (framerate difference e.g. 23.976 <-> 24.0/25.0 fps)
and quadratic drift models using pure Python numerical methods.
"""
import math
from typing import Any, Dict, List, Optional, Tuple


def _solve_3x3(A: List[List[float]], b: List[float]) -> Optional[List[float]]:
    """Solves A * x = b for 3x3 matrix using Gaussian elimination with partial pivoting."""
    n = 3
    # Augmented matrix [A | b]
    M = [[A[i][j] for j in range(n)] + [b[i]] for i in range(n)]

    for i in range(n):
        # Pivot
        max_row = i
        max_val = abs(M[i][i])
        for r in range(i + 1, n):
            if abs(M[r][i]) > max_val:
                max_val = abs(M[r][i])
                max_row = r
        if max_val < 1e-12:
            return None  # Singular or ill-conditioned
        M[i], M[max_row] = M[max_row], M[i]

        for r in range(i + 1, n):
            factor = M[r][i] / M[i][i]
            for c in range(i, n + 1):
                M[r][c] -= factor * M[i][c]

    # Back substitution
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        if abs(M[i][i]) < 1e-12:
            return None
        s = sum(M[i][j] * x[j] for j in range(i + 1, n))
        x[i] = (M[i][n] - s) / M[i][i]

    return x


class DriftModel:
    """
    Fits and applies linear (or quadratic) drift to subtitle cues.
    Offsets are defined as: offset(t) = ref_time - cue_time
    so ref_time = cue_time + offset(t).
    """

    @staticmethod
    def linear(t: float, a: float, b: float) -> float:
        return a * t + b

    @staticmethod
    def quadratic(t: float, a: float, b: float, c: float) -> float:
        return a * (t ** 2) + b * t + c

    @classmethod
    def fit_drift(cls, cue_times: List[float], ref_times: List[float]) -> Dict[str, Any]:
        """
        Fit linear (and optionally quadratic) drift model between cue_times and ref_times.
        Returns a dict: {"model": "linear" | "quadratic", "params": list, "rmse": float}
        """
        n = min(len(cue_times), len(ref_times))
        if n == 0:
            return {"model": "linear", "params": [0.0, 0.0], "rmse": 0.0}

        xs = [float(cue_times[i]) for i in range(n)]
        ys = [float(ref_times[i]) - float(cue_times[i]) for i in range(n)]

        if n == 1:
            return {"model": "linear", "params": [0.0, ys[0]], "rmse": 0.0}

        mean_x = sum(xs) / n
        mean_y = sum(ys) / n

        var_x = sum((x - mean_x) ** 2 for x in xs)

        if var_x < 1e-9:
            # Degenerate: all points at same time
            return {"model": "linear", "params": [0.0, mean_y], "rmse": 0.0}

        # Linear fit: y = a * x + b
        cov_xy = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
        lin_a = cov_xy / var_x
        lin_b = mean_y - lin_a * mean_x

        lin_errors = [ys[i] - (lin_a * xs[i] + lin_b) for i in range(n)]
        lin_rmse = math.sqrt(sum(e ** 2 for e in lin_errors) / n)

        # Check quadratic fit if n >= 6 and significant non-linearity might exist
        quad_rmse = float("inf")
        quad_params = None

        if n >= 6:
            sum_x = sum(xs)
            sum_x2 = sum(x ** 2 for x in xs)
            sum_x3 = sum(x ** 3 for x in xs)
            sum_x4 = sum(x ** 4 for x in xs)

            sum_y = sum(ys)
            sum_xy = sum(x * y for x, y in zip(xs, ys))
            sum_x2y = sum((x ** 2) * y for x, y in zip(xs, ys))

            # Fitting y = c2 * x^2 + c1 * x + c0
            A = [
                [sum_x4, sum_x3, sum_x2],
                [sum_x3, sum_x2, sum_x],
                [sum_x2, sum_x, float(n)],
            ]
            B = [sum_x2y, sum_xy, sum_y]

            sol = _solve_3x3(A, B)
            if sol is not None:
                c2, c1, c0 = sol
                quad_errors = [ys[i] - (c2 * (xs[i] ** 2) + c1 * xs[i] + c0) for i in range(n)]
                quad_rmse = math.sqrt(sum(e ** 2 for e in quad_errors) / n)
                quad_params = [c2, c1, c0]

        if quad_params is not None and quad_rmse < lin_rmse * 0.75:
            return {"model": "quadratic", "params": quad_params, "rmse": round(quad_rmse, 4)}

        return {"model": "linear", "params": [round(lin_a, 6), round(lin_b, 4)], "rmse": round(lin_rmse, 4)}

    @classmethod
    def apply_drift(cls, cue_times: List[float], model: Dict[str, Any]) -> List[float]:
        """
        Applies fitted drift model to adjust cue times.
        Returns corrected timestamps.
        """
        model_type = model.get("model", "linear")
        params = model.get("params", [0.0, 0.0])

        if model_type == "linear":
            a, b = params[0], params[1]
            return [round(t + (a * t + b), 3) for t in cue_times]
        elif model_type == "quadratic":
            a, b, c = params[0], params[1], params[2]
            return [round(t + (a * (t ** 2) + b * t + c), 3) for t in cue_times]

        return [round(t, 3) for t in cue_times]
