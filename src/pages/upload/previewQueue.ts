/** Per-workspace request budget. Clearing never releases running request slots. */
export function createPreviewQueue(concurrency = 4) {
  let active = 0;
  const waiting: Array<{ start: () => void; cancel: () => void }> = [];
  const drain = () => {
    while (active < concurrency && waiting.length) waiting.shift()!.start();
  };
  return {
    run<T>(work: () => Promise<T>): Promise<T | undefined> {
      return new Promise((resolve, reject) => {
        waiting.push({
          cancel: () => resolve(undefined),
          start: () => {
            active += 1;
            void Promise.resolve()
              .then(work)
              .then(resolve, reject)
              .finally(() => {
                active -= 1;
                drain();
              });
          },
        });
        drain();
      });
    },
    clear() {
      waiting.splice(0).forEach((item) => item.cancel());
    },
  };
}
