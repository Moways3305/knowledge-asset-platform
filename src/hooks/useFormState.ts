import { useCallback, useRef, useState } from "react";

// 表单字段收拢：把页面里成片的表单 useState（UploadPage / AdminWecomScanPage 等）
// 归并到一个对象里，提供 set（单字段）/ setMany（批量）/ reset（回到初值或指定值）。
// 初值用 ref 固定，使 reset 标识稳定（不随父组件每次渲染变化）。
export interface FormState<T> {
  values: T;
  set: <K extends keyof T>(key: K, value: T[K]) => void;
  setMany: (patch: Partial<T>) => void;
  reset: (next?: T) => void;
  setValues: React.Dispatch<React.SetStateAction<T>>;
}

export function useFormState<T extends Record<string, unknown>>(initial: T): FormState<T> {
  const initialRef = useRef(initial);
  const [values, setValues] = useState<T>(initial);

  const set = useCallback(<K extends keyof T>(key: K, value: T[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  }, []);

  const setMany = useCallback((patch: Partial<T>) => {
    setValues((prev) => ({ ...prev, ...patch }));
  }, []);

  const reset = useCallback((next?: T) => {
    setValues(next ?? initialRef.current);
  }, []);

  return { values, set, setMany, reset, setValues };
}
