// 使用绝对截止时间，后台节流后不补数“错过的 tick”。不跨刷新保存睡眠会话。
export class SleepTimer {
  constructor({ onUpdate, onExpire, now = Date.now,
    schedule = setTimeout, unschedule = clearTimeout }) {
    Object.assign(this, { onUpdate, onExpire, now, schedule, unschedule });
    this.deadline = null;
    this.timeout = null;
    this.onUpdate(null);
  }

  get active() { return this.deadline !== null; }

  start(minutes) {
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 180) return false;
    this.cancel();
    this.deadline = this.now() + minutes * 60000;
    this.check();
    return true;
  }

  cancel() {
    this.unschedule(this.timeout);
    this.timeout = null;
    this.deadline = null;
    this.onUpdate(null);
  }

  check() {
    if (!this.active) return false;
    this.unschedule(this.timeout);
    const remaining = this.deadline - this.now();
    if (remaining <= 0) {
      this.cancel();
      this.onExpire();
      return true;
    }
    this.onUpdate(Math.ceil(remaining / 1000));
    this.timeout = this.schedule(() => this.check(), Math.min(1000, remaining));
    return false;
  }
}
