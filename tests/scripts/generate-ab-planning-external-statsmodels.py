import json
import math

from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize

PLAN_MODE_MDE_FROM_N = "mde_from_n"
PLAN_MODE_N_FROM_MDE = "n_from_mde"
PLAN_DIR_TWO_SIDED = "two_sided"
PLAN_DIR_B_GT_A = "b_gt_a"
PLAN_DIR_B_LT_A = "b_lt_a"
MAX_SOLVER_N = 2_000_000_000

power_solver = NormalIndPower()


def clamp(value, lo, hi):
  return min(hi, max(lo, value))


def invert_effect_size_to_rate(base_rate, abs_effect_size, direction):
  if abs_effect_size <= 0:
    return base_rate

  if direction > 0:
    lo, hi = base_rate, 1.0
    boundary = hi
  else:
    lo, hi = 0.0, base_rate
    boundary = lo

  max_abs_h = abs(proportion_effectsize(base_rate, boundary))
  if abs_effect_size > max_abs_h + 1e-12:
    return math.inf

  for _ in range(90):
    mid = (lo + hi) / 2
    mid_abs_h = abs(proportion_effectsize(base_rate, mid))
    if mid_abs_h < abs_effect_size:
      if direction > 0:
        lo = mid
      else:
        hi = mid
    else:
      if direction > 0:
        hi = mid
      else:
        lo = mid

  return hi if direction > 0 else lo


def solve_mde_statsmodels(base_rate, n_per_group, alpha, target_power, direction):
  # We use a two-sided criterion to match the current app logic.
  abs_h = power_solver.solve_power(
    effect_size=None,
    nobs1=n_per_group,
    alpha=alpha,
    power=target_power,
    ratio=1.0,
    alternative="two-sided",
  )
  if not math.isfinite(abs_h):
    return math.inf

  target_rate = invert_effect_size_to_rate(base_rate, abs_h, direction)
  if not math.isfinite(target_rate):
    return math.inf
  return abs(target_rate - base_rate)


def solve_n_statsmodels(base_rate, mde_abs, alpha, target_power, direction):
  candidate_rate = base_rate + direction * mde_abs
  if candidate_rate < 0 or candidate_rate > 1:
    return math.inf

  abs_h = abs(proportion_effectsize(base_rate, candidate_rate))
  if abs_h <= 0:
    return 2

  n_value = power_solver.solve_power(
    effect_size=abs_h,
    nobs1=None,
    alpha=alpha,
    power=target_power,
    ratio=1.0,
    alternative="two-sided",
  )
  if not math.isfinite(n_value):
    return math.inf
  return min(MAX_SOLVER_N, math.ceil(n_value))


def normalize_direction_mode(raw):
  if raw == PLAN_DIR_B_LT_A:
    return PLAN_DIR_B_LT_A
  if raw == PLAN_DIR_TWO_SIDED:
    return PLAN_DIR_TWO_SIDED
  return PLAN_DIR_B_GT_A


def direction_meta(mode):
  if mode == PLAN_DIR_B_LT_A:
    return {"dir": -1, "two_sided": False}
  if mode == PLAN_DIR_TWO_SIDED:
    return {"dir": 0, "two_sided": True}
  return {"dir": 1, "two_sided": False}


def compute_reference(input_data):
  mode = PLAN_MODE_N_FROM_MDE if input_data["plannerMode"] == PLAN_MODE_N_FROM_MDE else PLAN_MODE_MDE_FROM_N
  direction_mode = normalize_direction_mode(input_data["planDirectionMode"])
  meta = direction_meta(direction_mode)

  base_rate = clamp(float(input_data["planBaseRate"]) / 100.0, 0.0, 1.0)
  alpha = float(input_data["planAlpha"])
  target_power = clamp(float(input_data["planTargetPower"]) / 100.0, 0.5, 0.9999)

  if mode == PLAN_MODE_MDE_FROM_N:
    n_per_group = max(2, round(float(input_data["planN"])))
    mde_up = solve_mde_statsmodels(base_rate, n_per_group, alpha, target_power, 1)
    mde_down = solve_mde_statsmodels(base_rate, n_per_group, alpha, target_power, -1)

    finite = [x for x in (mde_up, mde_down) if math.isfinite(x)]
    conservative_mde = max(finite) if finite else math.inf

    if math.isfinite(mde_up) and math.isfinite(mde_down):
      hardest_direction = 1 if mde_up >= mde_down else -1
    elif math.isfinite(mde_up):
      hardest_direction = 1
    elif math.isfinite(mde_down):
      hardest_direction = -1
    else:
      hardest_direction = 0

    selected_mde = conservative_mde
    selected_direction = hardest_direction

    if not meta["two_sided"]:
      if meta["dir"] > 0:
        selected_mde = mde_up
        selected_direction = 1
      else:
        selected_mde = mde_down
        selected_direction = -1

    return {
      "mode": mode,
      "directionMode": direction_mode,
      "selectedMde": selected_mde,
      "selectedDirection": selected_direction,
      "directionFeasible": math.isfinite(selected_mde),
    }

  mde_abs = abs(float(input_data["planMde"])) / 100.0
  up_feasible = base_rate + mde_abs <= 1
  down_feasible = base_rate - mde_abs >= 0
  n_up = solve_n_statsmodels(base_rate, mde_abs, alpha, target_power, 1) if up_feasible else math.inf
  n_down = solve_n_statsmodels(base_rate, mde_abs, alpha, target_power, -1) if down_feasible else math.inf

  finite_n = [x for x in (n_up, n_down) if math.isfinite(x)]
  conservative_required_n = max(finite_n) if finite_n else math.inf

  if math.isfinite(n_up) and math.isfinite(n_down):
    hardest_direction = 1 if n_up >= n_down else -1
  elif math.isfinite(n_up):
    hardest_direction = 1
  elif math.isfinite(n_down):
    hardest_direction = -1
  else:
    hardest_direction = 0

  selected_n = conservative_required_n
  selected_direction = hardest_direction
  if not meta["two_sided"]:
    if meta["dir"] > 0:
      selected_n = n_up
      selected_direction = 1
    else:
      selected_n = n_down
      selected_direction = -1

  return {
    "mode": mode,
    "directionMode": direction_mode,
    "requiredN": selected_n,
    "selectedDirection": selected_direction,
    "directionFeasible": math.isfinite(selected_n),
  }


def normalize_value(value, digits=12):
  if isinstance(value, bool):
    return value
  if isinstance(value, int):
    return value
  if isinstance(value, float):
    if math.isfinite(value):
      return round(value, digits)
    if value > 0:
      return "Infinity"
    if value < 0:
      return "-Infinity"
    return "NaN"
  return value


def normalize_dict(data):
  return {k: normalize_value(v) for k, v in data.items()}


cases = [
  {
    "id": "sm_mde_up_small_base",
    "input": {
      "plannerMode": PLAN_MODE_MDE_FROM_N,
      "planDirectionMode": PLAN_DIR_B_GT_A,
      "planBaseRate": 2,
      "planAlpha": 0.05,
      "planTargetPower": 80,
      "planN": 8000,
      "planMde": 1,
    },
  },
  {
    "id": "sm_mde_down_mid_base",
    "input": {
      "plannerMode": PLAN_MODE_MDE_FROM_N,
      "planDirectionMode": PLAN_DIR_B_LT_A,
      "planBaseRate": 15,
      "planAlpha": 0.05,
      "planTargetPower": 90,
      "planN": 25000,
      "planMde": 1,
    },
  },
  {
    "id": "sm_mde_two_sided_high_base",
    "input": {
      "plannerMode": PLAN_MODE_MDE_FROM_N,
      "planDirectionMode": PLAN_DIR_TWO_SIDED,
      "planBaseRate": 70,
      "planAlpha": 0.1,
      "planTargetPower": 80,
      "planN": 12000,
      "planMde": 1,
    },
  },
  {
    "id": "sm_mde_two_sided_mid_base",
    "input": {
      "plannerMode": PLAN_MODE_MDE_FROM_N,
      "planDirectionMode": PLAN_DIR_TWO_SIDED,
      "planBaseRate": 35,
      "planAlpha": 0.01,
      "planTargetPower": 85,
      "planN": 6000,
      "planMde": 1,
    },
  },
  {
    "id": "sm_n_up_typical",
    "input": {
      "plannerMode": PLAN_MODE_N_FROM_MDE,
      "planDirectionMode": PLAN_DIR_B_GT_A,
      "planBaseRate": 5,
      "planAlpha": 0.05,
      "planTargetPower": 80,
      "planN": 10000,
      "planMde": 1,
    },
  },
  {
    "id": "sm_n_down_typical",
    "input": {
      "plannerMode": PLAN_MODE_N_FROM_MDE,
      "planDirectionMode": PLAN_DIR_B_LT_A,
      "planBaseRate": 40,
      "planAlpha": 0.05,
      "planTargetPower": 85,
      "planN": 10000,
      "planMde": 2.5,
    },
  },
  {
    "id": "sm_n_two_sided_conservative",
    "input": {
      "plannerMode": PLAN_MODE_N_FROM_MDE,
      "planDirectionMode": PLAN_DIR_TWO_SIDED,
      "planBaseRate": 30,
      "planAlpha": 0.01,
      "planTargetPower": 90,
      "planN": 10000,
      "planMde": 1.2,
    },
  },
  {
    "id": "sm_n_low_effect_large_n",
    "input": {
      "plannerMode": PLAN_MODE_N_FROM_MDE,
      "planDirectionMode": PLAN_DIR_TWO_SIDED,
      "planBaseRate": 10,
      "planAlpha": 0.05,
      "planTargetPower": 95,
      "planN": 10000,
      "planMde": 0.3,
    },
  },
  {
    "id": "sm_n_up_not_feasible",
    "input": {
      "plannerMode": PLAN_MODE_N_FROM_MDE,
      "planDirectionMode": PLAN_DIR_B_GT_A,
      "planBaseRate": 98,
      "planAlpha": 0.05,
      "planTargetPower": 80,
      "planN": 10000,
      "planMde": 5,
    },
  },
  {
    "id": "sm_n_down_not_feasible",
    "input": {
      "plannerMode": PLAN_MODE_N_FROM_MDE,
      "planDirectionMode": PLAN_DIR_B_LT_A,
      "planBaseRate": 1,
      "planAlpha": 0.05,
      "planTargetPower": 80,
      "planN": 10000,
      "planMde": 2,
    },
  },
]

output = []
for case in cases:
  expected = compute_reference(case["input"])
  output.append({
    "id": case["id"],
    "source": "statsmodels 0.14.6 (NormalIndPower + proportion_effectsize)",
    "input": case["input"],
    "expected": normalize_dict(expected),
  })

print(json.dumps(output, ensure_ascii=False, indent=2))
