(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.AbPlanningCore = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const Z_BY_CONF = {
    90: 1.6448536269514722,
    95: 1.959963984540054,
    99: 2.5758293035489004,
  };

  const PLAN_MODE_MDE_FROM_N = "mde_from_n";
  const PLAN_MODE_N_FROM_MDE = "n_from_mde";
  const PLAN_DIR_TWO_SIDED = "two_sided";
  const PLAN_DIR_B_GT_A = "b_gt_a";
  const PLAN_DIR_B_LT_A = "b_lt_a";
  const MAX_SOLVER_N = 2000000000;

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function erf(x) {
    const sign = x >= 0 ? 1 : -1;
    const absX = Math.abs(x);
    const a1 = 0.254829592;
    const a2 = -0.284496736;
    const a3 = 1.421413741;
    const a4 = -1.453152027;
    const a5 = 1.061405429;
    const p = 0.3275911;

    const t = 1 / (1 + p * absX);
    const y = 1 - (((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t) * Math.exp(-absX * absX);
    return sign * y;
  }

  function normalCdf(x) {
    return 0.5 * (1 + erf(x / Math.SQRT2));
  }

  function twoSidedPower(delta, zCritical) {
    if (!Number.isFinite(delta) || !Number.isFinite(zCritical)) return 0;
    return clamp((1 - normalCdf(zCritical - delta)) + normalCdf(-zCritical - delta), 0, 1);
  }

  function seDiffForRates(pA, pB, nA, nB) {
    return Math.sqrt(Math.max((pA * (1 - pA)) / nA + (pB * (1 - pB)) / nB, 0));
  }

  function powerForRates(pA, pB, nA, nB, zCritical) {
    const seDiff = seDiffForRates(pA, pB, nA, nB);
    const diffAbs = Math.abs(pA - pB);
    if (seDiff > 0) return twoSidedPower(diffAbs / seDiff, zCritical);
    if (diffAbs > Number.EPSILON) return 1;
    return 0;
  }

  function solveMdeFromBaseRate(baseRate, nA, nB, targetPower, zCritical, direction) {
    if (![baseRate, nA, nB, targetPower, zCritical, direction].every(Number.isFinite)) return Infinity;
    const clippedTarget = clamp(targetPower, 0, 0.999999);
    const dir = direction >= 0 ? 1 : -1;
    const maxEffect = dir > 0 ? 1 - baseRate : baseRate;
    if (maxEffect <= 0) return Infinity;

    const maxPower = powerForRates(baseRate, baseRate + dir * maxEffect, nA, nB, zCritical);
    if (maxPower < clippedTarget) return Infinity;

    let lo = 0;
    let hi = maxEffect;
    for (let i = 0; i < 60; i++) {
      const mid = (lo + hi) / 2;
      const candidatePower = powerForRates(baseRate, baseRate + dir * mid, nA, nB, zCritical);
      if (candidatePower < clippedTarget) lo = mid;
      else hi = mid;
    }
    return hi;
  }

  function solveNForMde(baseRate, mdeAbs, targetPower, zCritical, direction) {
    if (![baseRate, mdeAbs, targetPower, zCritical, direction].every(Number.isFinite)) return Infinity;
    const clippedTarget = clamp(targetPower, 0, 0.999999);
    const effect = Math.abs(mdeAbs);
    if (effect <= 0) return 2;

    const dir = direction >= 0 ? 1 : -1;
    const candidateRate = baseRate + dir * effect;
    if (candidateRate < 0 || candidateRate > 1) return Infinity;

    const hasEnoughPower = (n) => powerForRates(baseRate, candidateRate, n, n, zCritical) >= clippedTarget;

    let lo = 2;
    let hi = 2;
    if (hasEnoughPower(hi)) return hi;

    while (!hasEnoughPower(hi) && hi < MAX_SOLVER_N) {
      lo = hi;
      hi = Math.min(MAX_SOLVER_N, hi * 2);
    }

    if (!hasEnoughPower(hi)) return Infinity;

    while (hi - lo > 1) {
      const mid = Math.floor((lo + hi) / 2);
      if (hasEnoughPower(mid)) hi = mid;
      else lo = mid;
    }
    return hi;
  }

  function normalizePlanDirectionMode(raw) {
    if (raw === PLAN_DIR_B_LT_A) return PLAN_DIR_B_LT_A;
    if (raw === PLAN_DIR_TWO_SIDED) return PLAN_DIR_TWO_SIDED;
    return PLAN_DIR_B_GT_A;
  }

  function getDirectionModeMeta(mode) {
    if (mode === PLAN_DIR_B_LT_A) {
      return {
        label: "B < A",
        description: "односторонний B < A",
        dir: -1,
        twoSided: false,
      };
    }
    if (mode === PLAN_DIR_TWO_SIDED) {
      return {
        label: "двусторонний",
        description: "двусторонний (консервативно)",
        dir: 0,
        twoSided: true,
      };
    }
    return {
      label: "B > A",
      description: "односторонний B > A",
      dir: 1,
      twoSided: false,
    };
  }

  function computePlanningStats(input) {
    const mode = input.plannerMode === PLAN_MODE_N_FROM_MDE
      ? PLAN_MODE_N_FROM_MDE
      : PLAN_MODE_MDE_FROM_N;
    const directionMode = normalizePlanDirectionMode(input.planDirectionMode);
    const directionMeta = getDirectionModeMeta(directionMode);
    const baseRate = clamp(Number(input.planBaseRate) / 100, 0, 1);
    const alphaRaw = Number(input.planAlpha);
    const alpha = Number.isFinite(alphaRaw) ? alphaRaw : 0.05;
    const targetPower = clamp(Number(input.planTargetPower) / 100, 0.5, 0.9999);
    const confidence = Math.round((1 - alpha) * 100);
    const z = Z_BY_CONF[confidence] || Z_BY_CONF[95];

    const common = {
      mode,
      baseRate,
      alpha,
      confidence,
      targetPower,
      z,
      directionMode,
      directionLabel: directionMeta.label,
      directionDescription: directionMeta.description,
    };

    if (mode === PLAN_MODE_MDE_FROM_N) {
      const nRaw = Number(input.planN);
      const nPerGroup = Number.isFinite(nRaw) ? Math.max(2, Math.round(nRaw)) : 2;
      const mdeUp = solveMdeFromBaseRate(baseRate, nPerGroup, nPerGroup, targetPower, z, 1);
      const mdeDown = solveMdeFromBaseRate(baseRate, nPerGroup, nPerGroup, targetPower, z, -1);
      const finiteMde = [mdeUp, mdeDown].filter(Number.isFinite);
      const conservativeMde = finiteMde.length > 0 ? Math.max(...finiteMde) : Infinity;
      const hardestDirection = Number.isFinite(mdeUp) && Number.isFinite(mdeDown)
        ? (mdeUp >= mdeDown ? 1 : -1)
        : (Number.isFinite(mdeUp) ? 1 : (Number.isFinite(mdeDown) ? -1 : 0));
      let selectedMde = conservativeMde;
      let selectedDirection = hardestDirection;
      if (!directionMeta.twoSided) {
        if (directionMeta.dir > 0) {
          selectedMde = mdeUp;
          selectedDirection = 1;
        } else {
          selectedMde = mdeDown;
          selectedDirection = -1;
        }
      }

      return {
        ...common,
        nPerGroup,
        mdeUp,
        mdeDown,
        conservativeMde,
        selectedMde,
        selectedDirection,
        hardestDirection,
        directionFeasible: Number.isFinite(selectedMde),
        upRate: Number.isFinite(mdeUp) ? baseRate + mdeUp : null,
        downRate: Number.isFinite(mdeDown) ? baseRate - mdeDown : null,
        selectedRate: Number.isFinite(selectedMde) && selectedDirection !== 0
          ? baseRate + selectedDirection * selectedMde
          : null,
      };
    }

    const mdeRaw = Math.abs(Number(input.planMde));
    const mdeAbs = Number.isFinite(mdeRaw) ? mdeRaw / 100 : 0;
    const upFeasible = baseRate + mdeAbs <= 1;
    const downFeasible = baseRate - mdeAbs >= 0;
    const nUp = upFeasible ? solveNForMde(baseRate, mdeAbs, targetPower, z, 1) : Infinity;
    const nDown = downFeasible ? solveNForMde(baseRate, mdeAbs, targetPower, z, -1) : Infinity;
    const finiteN = [nUp, nDown].filter(Number.isFinite);
    const conservativeRequiredN = finiteN.length > 0 ? Math.max(...finiteN) : Infinity;
    const hardestDirection = Number.isFinite(nUp) && Number.isFinite(nDown)
      ? (nUp >= nDown ? 1 : -1)
      : (Number.isFinite(nUp) ? 1 : (Number.isFinite(nDown) ? -1 : 0));
    let selectedN = conservativeRequiredN;
    let selectedDirection = hardestDirection;
    if (!directionMeta.twoSided) {
      if (directionMeta.dir > 0) {
        selectedN = nUp;
        selectedDirection = 1;
      } else {
        selectedN = nDown;
        selectedDirection = -1;
      }
    }
    const requiredN = selectedN;
    const totalN = Number.isFinite(selectedN) ? selectedN * 2 : Infinity;

    return {
      ...common,
      mdeAbs,
      upFeasible,
      downFeasible,
      nUp,
      nDown,
      selectedN,
      selectedDirection,
      requiredN,
      conservativeRequiredN,
      totalN,
      hardestDirection,
      directionFeasible: Number.isFinite(selectedN),
    };
  }

  return {
    Z_BY_CONF,
    PLAN_MODE_MDE_FROM_N,
    PLAN_MODE_N_FROM_MDE,
    PLAN_DIR_TWO_SIDED,
    PLAN_DIR_B_GT_A,
    PLAN_DIR_B_LT_A,
    MAX_SOLVER_N,
    clamp,
    normalCdf,
    powerForRates,
    solveMdeFromBaseRate,
    solveNForMde,
    normalizePlanDirectionMode,
    getDirectionModeMeta,
    computePlanningStats,
  };
});
