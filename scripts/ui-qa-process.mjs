export function waitForChildProcess(
  child,
  { timeoutMs, forceKillAfterMs = 5_000, timeoutMessage },
) {
  return new Promise((resolve) => {
    let output = "";
    let timedOut = false;
    let forceKillTimer = null;
    const collect = (chunk) => {
      output = `${output}${chunk.toString()}`.slice(-8000);
    };
    child.stdout?.on("data", collect);
    child.stderr?.on("data", collect);

    const timeout = setTimeout(() => {
      if (child.exitCode !== null) return;
      timedOut = true;
      output = `${output}\n${timeoutMessage}`;
      child.kill("SIGTERM");
      forceKillTimer = setTimeout(() => {
        if (child.exitCode === null) child.kill("SIGKILL");
      }, forceKillAfterMs);
    }, timeoutMs);

    child.once("close", (code) => {
      clearTimeout(timeout);
      if (forceKillTimer) clearTimeout(forceKillTimer);
      resolve({ code: timedOut ? 1 : (code ?? 1), output, timedOut });
    });
  });
}
