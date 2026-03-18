import json
import math

Z_BY_CONF = {
  90: 1.6448536269514722,
  95: 1.959963984540054,
  99: 2.5758293035489004,
}

PLAN_MODE_MDE_FROM_N = "mde_from_n"
PLAN_MODE_N_FROM_MDE = "n_from_mde"
PLAN_DIR_TWO_SIDED = "two_sided"
PLAN_DIR_B_GT_A = "b_gt_a"
PLAN_DIR_B_LT_A = "b_lt_a"
MAX_SOLVER_N = 2_000_000_000


def clamp(v, lo, hi):
  return min(hi, max(lo, v))


def normal_cdf(x):
  return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def two_sided_power(delta, z):
  if not math.isfinite(delta) or not math.isfinite(z):
    return 0.0
  return clamp((1 - normal_cdf(z - delta)) + normal_cdf(-z - delta), 0.0, 1.0)


def power_for_rates(p_a, p_b, n_a, n_b, z):
  se_diff = math.sqrt(max((p_a * (1 - p_a)) / n_a + (p_b * (1 - p_b)) / n_b, 0.0))
  diff_abs = abs(p_a - p_b)
  if se_diff > 0:
    return two_sided_power(diff_abs / se_diff, z)
  if diff_abs > float.fromhex('0x1.0000000000000p-52'):
    return 1.0
  return 0.0


def solve_mde_from_base_rate(base_rate, n_a, n_b, target_power, z, direction):
  vals = [base_rate, n_a, n_b, target_power, z, direction]
  if not all(math.isfinite(x) for x in vals):
    return math.inf
  clipped_target = clamp(target_power, 0.0, 0.999999)
  d = 1 if direction >= 0 else -1
  max_effect = (1 - base_rate) if d > 0 else base_rate
  if max_effect <= 0:
    return math.inf

  max_power = power_for_rates(base_rate, base_rate + d * max_effect, n_a, n_b, z)
  if max_power < clipped_target:
    return math.inf

  lo, hi = 0.0, max_effect
  for _ in range(80):
    mid = (lo + hi) / 2
    candidate_power = power_for_rates(base_rate, base_rate + d * mid, n_a, n_b, z)
    if candidate_power < clipped_target:
      lo = mid
    else:
      hi = mid
  return hi


def solve_n_for_mde(base_rate, mde_abs, target_power, z, direction):
  vals = [base_rate, mde_abs, target_power, z, direction]
  if not all(math.isfinite(x) for x in vals):
    return math.inf

  clipped_target = clamp(target_power, 0.0, 0.999999)
  effect = abs(mde_abs)
  if effect <= 0:
    return 2

  d = 1 if direction >= 0 else -1
  candidate_rate = base_rate + d * effect
  if candidate_rate < 0 or candidate_rate > 1:
    return math.inf

  def enough(n):
    return power_for_rates(base_rate, candidate_rate, n, n, z) >= clipped_target

  lo, hi = 2, 2
  if enough(hi):
    return hi

  while not enough(hi) and hi < MAX_SOLVER_N:
    lo = hi
    hi = min(MAX_SOLVER_N, hi * 2)

  if not enough(hi):
    return math.inf

  while hi - lo > 1:
    mid = (lo + hi) // 2
    if enough(mid):
      hi = mid
    else:
      lo = mid
  return hi


def normalize_dir(raw):
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


def compute_planning_stats(inp):
  mode = PLAN_MODE_N_FROM_MDE if inp["plannerMode"] == PLAN_MODE_N_FROM_MDE else PLAN_MODE_MDE_FROM_N
  dir_mode = normalize_dir(inp["planDirectionMode"])
  meta = direction_meta(dir_mode)
  base_rate = clamp(float(inp["planBaseRate"]) / 100.0, 0.0, 1.0)
  alpha = float(inp["planAlpha"])
  target_power = clamp(float(inp["planTargetPower"]) / 100.0, 0.5, 0.9999)
  confidence = round((1 - alpha) * 100)
  z = Z_BY_CONF.get(confidence, Z_BY_CONF[95])

  if mode == PLAN_MODE_MDE_FROM_N:
    n_per_group = max(2, round(float(inp["planN"])))
    mde_up = solve_mde_from_base_rate(base_rate, n_per_group, n_per_group, target_power, z, 1)
    mde_down = solve_mde_from_base_rate(base_rate, n_per_group, n_per_group, target_power, z, -1)
    finite = [x for x in (mde_up, mde_down) if math.isfinite(x)]
    conservative = max(finite) if finite else math.inf
    if math.isfinite(mde_up) and math.isfinite(mde_down):
      hardest = 1 if mde_up >= mde_down else -1
    elif math.isfinite(mde_up):
      hardest = 1
    elif math.isfinite(mde_down):
      hardest = -1
    else:
      hardest = 0

    selected_mde = conservative
    selected_dir = hardest
    if not meta["two_sided"]:
      if meta["dir"] > 0:
        selected_mde = mde_up
        selected_dir = 1
      else:
        selected_mde = mde_down
        selected_dir = -1

    return {
      "mode": mode,
      "directionMode": dir_mode,
      "baseRate": base_rate,
      "targetPower": target_power,
      "alpha": alpha,
      "z": z,
      "nPerGroup": n_per_group,
      "mdeUp": mde_up,
      "mdeDown": mde_down,
      "selectedMde": selected_mde,
      "selectedDirection": selected_dir,
      "hardestDirection": hardest,
      "directionFeasible": math.isfinite(selected_mde),
    }

  mde_abs = abs(float(inp["planMde"])) / 100.0
  up_feasible = base_rate + mde_abs <= 1
  down_feasible = base_rate - mde_abs >= 0
  n_up = solve_n_for_mde(base_rate, mde_abs, target_power, z, 1) if up_feasible else math.inf
  n_down = solve_n_for_mde(base_rate, mde_abs, target_power, z, -1) if down_feasible else math.inf
  finite_n = [x for x in (n_up, n_down) if math.isfinite(x)]
  conservative_n = max(finite_n) if finite_n else math.inf

  if math.isfinite(n_up) and math.isfinite(n_down):
    hardest = 1 if n_up >= n_down else -1
  elif math.isfinite(n_up):
    hardest = 1
  elif math.isfinite(n_down):
    hardest = -1
  else:
    hardest = 0

  selected_n = conservative_n
  selected_dir = hardest
  if not meta["two_sided"]:
    if meta["dir"] > 0:
      selected_n = n_up
      selected_dir = 1
    else:
      selected_n = n_down
      selected_dir = -1

  return {
    "mode": mode,
    "directionMode": dir_mode,
    "baseRate": base_rate,
    "targetPower": target_power,
    "alpha": alpha,
    "z": z,
    "mdeAbs": mde_abs,
    "upFeasible": up_feasible,
    "downFeasible": down_feasible,
    "nUp": n_up,
    "nDown": n_down,
    "requiredN": selected_n,
    "selectedDirection": selected_dir,
    "hardestDirection": hardest,
    "directionFeasible": math.isfinite(selected_n),
  }


def round_or_inf(x, digits=12):
  if isinstance(x, bool):
    return x
  if isinstance(x, int):
    return x
  if isinstance(x, float):
    if math.isfinite(x):
      return round(x, digits)
    if x > 0:
      return "Infinity"
    if x < 0:
      return "-Infinity"
    return "NaN"
  return x


def sanitize(obj):
  out = {}
  for k, v in obj.items():
    out[k] = round_or_inf(v)
  return out


cases = [
  {
    "id": "mde_small_base_up",
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
    "id": "mde_mid_base_down",
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
    "id": "mde_two_sided_high_base",
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
    "id": "mde_boundary_only_down",
    "input": {
      "plannerMode": PLAN_MODE_MDE_FROM_N,
      "planDirectionMode": PLAN_DIR_TWO_SIDED,
      "planBaseRate": 99.9,
      "planAlpha": 0.05,
      "planTargetPower": 80,
      "planN": 5000,
      "planMde": 1,
    },
  },
  {
    "id": "n_up_typical",
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
    "id": "n_down_typical",
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
    "id": "n_two_sided_conservative",
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
    "id": "n_up_not_feasible",
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
    "id": "n_down_not_feasible",
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
  {
    "id": "n_low_effect_large_n",
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
]

output = []
for case in cases:
  result = compute_planning_stats(case["input"])
  output.append({
    "id": case["id"],
    "input": case["input"],
    "expected": sanitize(result),
  })

print(json.dumps(output, ensure_ascii=False, indent=2))
