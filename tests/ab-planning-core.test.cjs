const test = require('node:test');
const assert = require('node:assert/strict');

const core = require('../js/ab-planning-core.js');

const baseInput = {
  plannerMode: core.PLAN_MODE_MDE_FROM_N,
  planDirectionMode: core.PLAN_DIR_B_GT_A,
  planBaseRate: 5,
  planAlpha: 0.05,
  planTargetPower: 80,
  planN: 10000,
  planMde: 1,
};

function planningStats(overrides = {}) {
  return core.computePlanningStats({ ...baseInput, ...overrides });
}

test('MDE decreases when sample size per group grows', () => {
  const lowN = planningStats({
    plannerMode: core.PLAN_MODE_MDE_FROM_N,
    planDirectionMode: core.PLAN_DIR_B_GT_A,
    planN: 5000,
  });
  const highN = planningStats({
    plannerMode: core.PLAN_MODE_MDE_FROM_N,
    planDirectionMode: core.PLAN_DIR_B_GT_A,
    planN: 50000,
  });

  assert.ok(Number.isFinite(lowN.selectedMde));
  assert.ok(Number.isFinite(highN.selectedMde));
  assert.ok(highN.selectedMde < lowN.selectedMde);
});

test('Required N increases when target MDE gets smaller', () => {
  const largerMde = planningStats({
    plannerMode: core.PLAN_MODE_N_FROM_MDE,
    planDirectionMode: core.PLAN_DIR_B_GT_A,
    planMde: 2.0,
  });
  const smallerMde = planningStats({
    plannerMode: core.PLAN_MODE_N_FROM_MDE,
    planDirectionMode: core.PLAN_DIR_B_GT_A,
    planMde: 0.5,
  });

  assert.ok(Number.isFinite(largerMde.requiredN));
  assert.ok(Number.isFinite(smallerMde.requiredN));
  assert.ok(smallerMde.requiredN > largerMde.requiredN);
});

test('Two-sided mode is conservative for MDE-from-N', () => {
  const stats = planningStats({
    plannerMode: core.PLAN_MODE_MDE_FROM_N,
    planDirectionMode: core.PLAN_DIR_TWO_SIDED,
    planBaseRate: 12,
    planN: 15000,
  });

  assert.ok(Number.isFinite(stats.mdeUp));
  assert.ok(Number.isFinite(stats.mdeDown));
  assert.equal(stats.selectedMde, Math.max(stats.mdeUp, stats.mdeDown));
  assert.equal(stats.selectedDirection, stats.hardestDirection);
});

test('Two-sided mode is conservative for N-from-MDE', () => {
  const stats = planningStats({
    plannerMode: core.PLAN_MODE_N_FROM_MDE,
    planDirectionMode: core.PLAN_DIR_TWO_SIDED,
    planBaseRate: 12,
    planMde: 1.2,
  });

  assert.ok(Number.isFinite(stats.nUp));
  assert.ok(Number.isFinite(stats.nDown));
  assert.equal(stats.requiredN, Math.max(stats.nUp, stats.nDown));
  assert.equal(stats.selectedDirection, stats.hardestDirection);
});

test('Direction feasibility is respected near conversion boundaries', () => {
  const upDirection = planningStats({
    plannerMode: core.PLAN_MODE_N_FROM_MDE,
    planDirectionMode: core.PLAN_DIR_B_GT_A,
    planBaseRate: 98,
    planMde: 5,
  });
  const downDirection = planningStats({
    plannerMode: core.PLAN_MODE_N_FROM_MDE,
    planDirectionMode: core.PLAN_DIR_B_LT_A,
    planBaseRate: 98,
    planMde: 5,
  });

  assert.equal(upDirection.upFeasible, false);
  assert.equal(upDirection.requiredN, Infinity);
  assert.equal(upDirection.directionFeasible, false);

  assert.equal(downDirection.downFeasible, true);
  assert.ok(Number.isFinite(downDirection.requiredN));
  assert.equal(downDirection.directionFeasible, true);
});

test('Solver consistency: n_from_mde and mde_from_n match on threshold', () => {
  const baseRate = 0.07;
  const mdeAbs = 0.012;
  const targetPower = 0.8;
  const z = core.Z_BY_CONF[95];

  const n = core.solveNForMde(baseRate, mdeAbs, targetPower, z, 1);
  assert.ok(Number.isFinite(n));

  const mdeAtN = core.solveMdeFromBaseRate(baseRate, n, n, targetPower, z, 1);
  assert.ok(Number.isFinite(mdeAtN));
  assert.ok(mdeAtN <= mdeAbs + 1e-9);

  if (n > 2) {
    const mdeAtPrevN = core.solveMdeFromBaseRate(baseRate, n - 1, n - 1, targetPower, z, 1);
    assert.ok(Number.isFinite(mdeAtPrevN));
    assert.ok(mdeAtPrevN >= mdeAbs - 1e-9);
  }
});

test('At 50% baseline, upward and downward MDE are symmetric', () => {
  const stats = planningStats({
    plannerMode: core.PLAN_MODE_MDE_FROM_N,
    planDirectionMode: core.PLAN_DIR_TWO_SIDED,
    planBaseRate: 50,
    planN: 20000,
  });

  assert.ok(Number.isFinite(stats.mdeUp));
  assert.ok(Number.isFinite(stats.mdeDown));
  assert.ok(Math.abs(stats.mdeUp - stats.mdeDown) < 1e-9);
});

test('Unknown direction falls back to B > A', () => {
  assert.equal(core.normalizePlanDirectionMode('unknown'), core.PLAN_DIR_B_GT_A);
});
