import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SleepTimer } from '../sleep-timer.mjs';

function fixture() {
  let now = 1000, expired = 0, displayed;
  const tasks = new Map();
  let id = 0;
  const timer = new SleepTimer({
    now: () => now,
    schedule: (fn) => { tasks.set(++id, fn); return id; },
    unschedule: (id) => tasks.delete(id),
    onUpdate: (seconds) => { displayed = seconds; },
    onExpire: () => { expired++; }
  });
  return { timer, tasks, advance: (ms) => { now += ms; },
    get displayed() { return displayed; }, get expired() { return expired; } };
}

test('validates durations without disturbing an existing timer', () => {
  const f = fixture();
  assert.equal(f.timer.start(30), true);
  for (const invalid of [0, -1, 181, 1.5, NaN, Infinity]) {
    assert.equal(f.timer.start(invalid), false);
  }
  assert.equal(f.displayed, 1800);
  assert.equal(f.tasks.size, 1);
});
test('counts wall time and expires once after a suspended page resumes', () => {
  const f = fixture();
  f.timer.start(1);
  f.advance(1500);
  f.timer.check();
  assert.equal(f.displayed, 59);
  f.advance(120000);
  assert.equal(f.timer.check(), true);
  f.timer.check();
  assert.equal(f.expired, 1);
  assert.equal(f.timer.active, false);
  assert.equal(f.tasks.size, 0);
});
test('reset replaces the deadline; cancellation leaves no expiry callback', () => {
  const f = fixture();
  f.timer.start(1);
  f.advance(59000);
  f.timer.start(2);
  f.advance(1000);
  f.timer.check();
  assert.equal(f.displayed, 119);
  assert.equal(f.tasks.size, 1);
  f.timer.cancel();
  f.advance(180000);
  f.timer.check();
  assert.equal(f.expired, 0);
  assert.equal(f.displayed, null);
  assert.equal(f.tasks.size, 0);
});
