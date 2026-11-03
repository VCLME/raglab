import { useSyncExternalStore } from "react";

const STORAGE_KEY = "raglab.educationalMode";
const listeners = new Set<() => void>();

function read(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "on";
  } catch {
    return false;
  }
}

let current = read();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setEducationalMode(on: boolean) {
  current = on;
  try {
    localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
  } catch {
    // private mode: keep the in-memory value
  }
  listeners.forEach((listener) => listener());
}

/** « Mode pédagogique » toggle, shared by the top bar and the Chat, persisted in localStorage. */
export function useEducationalMode(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, () => current);
  return [on, setEducationalMode];
}
