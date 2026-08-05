import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Check, ChevronDown } from "lucide-react";
import "./ProviderSelect.css";

export interface ProviderSelectOption {
  value: string;
  label: string;
  description?: string;
  icon?: ReactNode;
}

// 自定义供应商下拉：原生 <select> 的 <option> 无法渲染图标，故用
// "按钮触发器 + 弹出列表" 实现。键盘：方向键移动 / 回车选择 / Esc 关闭 / Home / End。
export default function ProviderSelect({
  options,
  value,
  onChange,
  placeholder = "请选择供应商",
  disabled = false,
  ariaLabel,
}: {
  options: ProviderSelectOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  ariaLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listboxId = useId();
  const selectedIndex = value ? options.findIndex((option) => option.value === value) : -1;
  const selected = selectedIndex >= 0 ? options[selectedIndex] : undefined;

  useEffect(() => {
    if (!open) return;
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
    const onDown = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, selectedIndex]);

  const selectOption = (option: ProviderSelectOption) => {
    onChange(option.value);
    setOpen(false);
    triggerRef.current?.focus();
  };

  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Enter") {
      event.preventDefault();
      setOpen(true);
    } else if (event.key === " ") {
      event.preventDefault();
      setOpen(true);
    }
  };

  const onListKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => (current + 1) % Math.max(options.length, 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => (current - 1 + options.length) % Math.max(options.length, 1));
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      setActiveIndex(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      setActiveIndex(Math.max(0, options.length - 1));
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      const option = options[activeIndex];
      if (option) selectOption(option);
    }
    if (event.key === "Tab") setOpen(false);
  };

  return (
    <div className="provider-select" ref={wrapRef}>
      <button
        type="button"
        ref={triggerRef}
        className="provider-select-trigger"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={ariaLabel}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={onTriggerKeyDown}
      >
        {selected ? (
          <>
            {selected.icon}
            <span className="provider-select-trigger-label">{selected.label}</span>
          </>
        ) : (
          <span className="provider-select-placeholder">{placeholder}</span>
        )}
        <ChevronDown size={14} className="provider-select-chevron" aria-hidden="true" />
      </button>

      {open && (
        <ul
          id={listboxId}
          className="provider-select-list"
          role="listbox"
          aria-label={ariaLabel}
          onKeyDown={onListKeyDown}
        >
          {options.map((option, index) => (
            <li
              key={option.value}
              role="option"
              aria-selected={option.value === value}
              className={`provider-select-option ${
                index === activeIndex ? "is-active" : ""
              } ${option.value === value ? "is-selected" : ""}`}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => selectOption(option)}
            >
              {option.icon}
              <span className="provider-select-option-copy">
                <strong>{option.label}</strong>
                {option.description && <small>{option.description}</small>}
              </span>
              {option.value === value && <Check size={14} className="provider-select-check" />}
            </li>
          ))}
          {options.length === 0 && (
            <li className="provider-select-empty" role="option" aria-disabled="true">
              暂无可选供应商
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
