// Local-first pending queue: every mutating call is saved to localStorage
// *before* it's sent. It's only removed once the server confirms success.
// The server-side idempotency_key means a retried/duplicated send is safe.
(function (global) {
  function AttendanceQueue(opts) {
    this.storageKey = opts.storageKey;
    this.onCountChange = opts.onCountChange || function () {};
    this._flushing = false;
    this._flushPending = false;
    window.addEventListener("online", () => this.flush());
    setInterval(() => this.flush(), 15000);
    this.flush();
  }

  AttendanceQueue.prototype._load = function () {
    try {
      return JSON.parse(localStorage.getItem(this.storageKey) || "[]");
    } catch (e) {
      return [];
    }
  };

  AttendanceQueue.prototype._save = function (items) {
    localStorage.setItem(this.storageKey, JSON.stringify(items));
    this.onCountChange(items.length);
  };

  AttendanceQueue.prototype.enqueue = function (url, body) {
    const items = this._load();
    items.push({ url, body, createdAt: Date.now() });
    this._save(items);
    this.flush();
  };

  AttendanceQueue.prototype.pendingCount = function () {
    return this._load().length;
  };

  AttendanceQueue.prototype.flush = async function () {
    if (this._flushing) {
      this._flushPending = true;
      return;
    }
    this._flushing = true;
    try {
      do {
        this._flushPending = false;
        const items = this._load();
        if (items.length === 0) break;
        const remaining = [];
        for (const item of items) {
          try {
            const resp = await fetch(item.url, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(item.body),
            });
            if (!resp.ok) throw new Error("http " + resp.status);
          } catch (e) {
            remaining.push(item);
          }
        }
        this._save(remaining);
      } while (this._flushPending);
    } finally {
      this._flushing = false;
    }
  };

  global.AttendanceQueue = AttendanceQueue;
})(window);
