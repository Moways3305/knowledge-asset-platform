import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import DetailDrawer from "../DetailDrawer";
import { ApiError } from "../../api/http";
import "./operations.css";

export function operationError(error: unknown) {
  return error instanceof ApiError ? error.message : "操作未完成，请重试。";
}
const BusyContext = createContext<{ busy: boolean; setBusy: (busy: boolean) => void }>({
  busy: false,
  setBusy: () => {},
});

// Mount content only while open: closed drawers retain neither private results nor credentials.
export function OperationPanel({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <button type="button" className="btn-small" onClick={() => setOpen(true)}>
        {label}
      </button>
      {open && (
        <DetailDrawer
          open
          title={label}
          busy={busy}
          onClose={() => setOpen(false)}
          portal
          className="operation-drawer"
        >
          <BusyContext.Provider value={{ busy, setBusy }}>
            <fieldset className="operation-content operation-lock" disabled={busy}>
              {children}
            </fieldset>
          </BusyContext.Provider>
        </DetailDrawer>
      )}
    </>
  );
}

export function ReadResult<T>({
  load,
  children,
  refreshLabel = "刷新",
}: {
  load: () => Promise<T>;
  children: (data: T) => ReactNode;
  refreshLabel?: string | false;
}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const loader = useRef(load);
  loader.current = load;
  useEffect(() => {
    let live = true;
    setData(null);
    setError("");
    void loader
      .current()
      .then((result) => {
        if (live) setData(result);
      })
      .catch((reason) => {
        if (live) setError(operationError(reason));
      });
    return () => {
      live = false;
    };
  }, [attempt]);
  return (
    <div className="operation-content">
      {error ? (
        <p role="alert">
          {error}{" "}
          <button type="button" className="btn-small" onClick={() => setAttempt((n) => n + 1)}>
            重试
          </button>
        </p>
      ) : data === null ? (
        <p role="status">正在加载…</p>
      ) : (
        <>
          {refreshLabel && (
            <div className="operation-actions">
              <button type="button" className="btn-small" onClick={() => setAttempt((n) => n + 1)}>
                {refreshLabel}
              </button>
            </div>
          )}
          {children(data)}
        </>
      )}
    </div>
  );
}

export function useOperation() {
  const parent = useContext(BusyContext);
  const lock = useRef(false);
  const mounted = useRef(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  async function run(action: () => Promise<string>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    parent.setBusy(true);
    setMessage("");
    setError("");
    try {
      const result = await action();
      if (mounted.current) setMessage(result);
    } catch (reason) {
      if (mounted.current) setError(operationError(reason));
    } finally {
      lock.current = false;
      parent.setBusy(false);
      if (mounted.current) setBusy(false);
    }
  }
  return {
    busy,
    run,
    feedback: (
      <>
        {error && <p role="alert">{error}</p>}
        {message && <p role="status">{message}</p>}
      </>
    ),
  };
}
