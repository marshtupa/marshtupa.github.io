const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const core = require('../js/ab-planning-core.js');

const fixturePath = path.join(__dirname, 'fixtures', 'ab-planning-golden.json');
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));

function fromJsonNumber(value) {
  if (value === 'Infinity') return Infinity;
  if (value === '-Infinity') return -Infinity;
  if (value === 'NaN') return NaN;
  return value;
}

function expectClose(actual, expected, context) {
  const exp = fromJsonNumber(expected);
  if (typeof exp === 'number' && Number.isFinite(exp)) {
    assert.equal(typeof actual, 'number', `${context}: actual is not a number`);
    const scale = Math.max(1, Math.abs(exp));
    const tolerance = 5e-7 * scale;
    assert.ok(
      Math.abs(actual - exp) <= tolerance,
      `${context}: expected ${exp}, got ${actual}, tolerance ${tolerance}`
    );
    return;
  }
  if (typeof exp === 'number' && Number.isNaN(exp)) {
    assert.ok(Number.isNaN(actual), `${context}: expected NaN, got ${actual}`);
    return;
  }
  assert.equal(actual, exp, `${context}: expected ${exp}, got ${actual}`);
}

test('golden fixture has enough scenario coverage', () => {
  assert.ok(Array.isArray(fixture));
  assert.ok(fixture.length >= 10, `expected >=10 golden cases, got ${fixture.length}`);

  const modes = new Set(fixture.map((entry) => entry.input.plannerMode));
  assert.ok(modes.has(core.PLAN_MODE_MDE_FROM_N), 'missing mde_from_n golden cases');
  assert.ok(modes.has(core.PLAN_MODE_N_FROM_MDE), 'missing n_from_mde golden cases');

  const dirs = new Set(fixture.map((entry) => entry.input.planDirectionMode));
  assert.ok(dirs.has(core.PLAN_DIR_B_GT_A), 'missing B > A golden cases');
  assert.ok(dirs.has(core.PLAN_DIR_B_LT_A), 'missing B < A golden cases');
  assert.ok(dirs.has(core.PLAN_DIR_TWO_SIDED), 'missing two-sided golden cases');
});

test('computePlanningStats matches golden reference cases', () => {
  for (const entry of fixture) {
    const actual = core.computePlanningStats(entry.input);
    const expected = entry.expected;

    for (const [key, expectedValue] of Object.entries(expected)) {
      expectClose(actual[key], expectedValue, `${entry.id}.${key}`);
    }
  }
});
