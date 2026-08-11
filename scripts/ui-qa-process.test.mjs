import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";
import { waitForChildProcess } from "./ui-qa-process.mjs";

test("a timed-out child does not settle until its close event", async () => {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.exitCode = null;
  const kills = [];
  child.kill = (signal) => {
    kills.push(signal);
    return true;
  };

  let settled = false;
  const completion = waitForChildProcess(child, {
    timeoutMs: 1,
    forceKillAfterMs: 100,
    timeoutMessage: "suite timed out",
  }).then((result) => {
    settled = true;
    return result;
  });

  await new Promise((resolve) => setTimeout(resolve, 15));
  assert.deepEqual(kills, ["SIGTERM"]);
  assert.equal(settled, false);

  child.exitCode = 143;
  child.emit("close", 143);
  const result = await completion;
  assert.equal(result.code, 1);
  assert.equal(result.timedOut, true);
  assert.match(result.output, /suite timed out/);
});

test("a child still running after the grace period is force-killed before settling", async () => {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.exitCode = null;
  const kills = [];
  child.kill = (signal) => {
    kills.push(signal);
    return true;
  };

  const completion = waitForChildProcess(child, {
    timeoutMs: 1,
    forceKillAfterMs: 10,
    timeoutMessage: "suite timed out",
  });
  const deadline = Date.now() + 250;
  while (kills.length < 2 && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  assert.deepEqual(kills, ["SIGTERM", "SIGKILL"]);

  child.exitCode = 137;
  child.emit("close", 137);
  assert.equal((await completion).timedOut, true);
});
