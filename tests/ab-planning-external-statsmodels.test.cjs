const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const core = require('../js/ab-planning-core.js');

const fixturePath = path.join(__dirname, 'fixtures', 'ab-planning-external-statsmodels.json');
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));

function fromJsonNumber(value) {
  if (value === 'Infinity') return Infinity;
  if (value === '-Infinity') return -Infinity;
  if (value === 'NaN') return NaN;
  return value;
}

function expectApprox(actual, expectedRaw, context, key) {
  const expected = fromJsonNumber(expectedRaw);

  if (typeof expected === 'number' && Number.isFinite(expected)) {
    assert.equal(typeof actual, 'number', `${context}: actual is not a number`);

    let relTol = 0.1;
    let absTol = 50;
    if (key.toLowerCase().includes('mde')) {
      relTol = 0.08;
      absTol = 0.001;
    }

    const relErr = Math.abs(actual - expected) / Math.max(Math.abs(expected), 1e-12);
    const absErr = Math.abs(actual - expected);
    assert.ok(
      relErr <= relTol || absErr <= absTol,
      `${context}: expected ${expected}, got ${actual}, relErr=${relErr}, absErr=${absErr}`
    );
    return;
  }

  if (typeof expected === 'number' && Number.isNaN(expected)) {
    assert.ok(Number.isNaN(actual), `${context}: expected NaN, got ${actual}`);
    return;
  }

  assert.equal(actual, expected, `${context}: expected ${expected}, got ${actual}`);
}

test('external statsmodels fixture coverage', () => {
  assert.ok(Array.isArray(fixture));
  assert.ok(fixture.length >= 10, `expected >=10 external cases, got ${fixture.length}`);

  const modes = new Set(fixture.map((entry) => entry.input.plannerMode));
  assert.ok(modes.has(core.PLAN_MODE_MDE_FROM_N), 'missing mde_from_n cases');
  assert.ok(modes.has(core.PLAN_MODE_N_FROM_MDE), 'missing n_from_mde cases');

  const dirs = new Set(fixture.map((entry) => entry.input.planDirectionMode));
  assert.ok(dirs.has(core.PLAN_DIR_B_GT_A), 'missing B > A cases');
  assert.ok(dirs.has(core.PLAN_DIR_B_LT_A), 'missing B < A cases');
  assert.ok(dirs.has(core.PLAN_DIR_TWO_SIDED), 'missing two-sided cases');
});

test('planning core is close to independent statsmodels references', () => {
  for (const entry of fixture) {
    const actual = core.computePlanningStats(entry.input);

    for (const [key, expectedValue] of Object.entries(entry.expected)) {
      expectApprox(actual[key], expectedValue, `${entry.id}.${key}`, key);
    }
  }
});
