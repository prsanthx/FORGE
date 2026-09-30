export type ThemeChoice = "light" | "dark" | "system";

const KEY = "forge-theme";

export function readTheme(): ThemeChoice {
  const stored = localStorage.getItem(KEY);
  if (stored === "light" || stored === "dark" || stored === "system") return stored;
  return "system";
}

export function resolveDark(choice: ThemeChoice): boolean {
  if (choice === "dark") return true;
  if (choice === "light") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function applyTheme(choice: ThemeChoice): void {
  const dark = resolveDark(choice);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

export function saveTheme(choice: ThemeChoice): void {
  localStorage.setItem(KEY, choice);
  applyTheme(choice);
  window.dispatchEvent(new Event("forge-theme"));
}

const CONFIG_KEY = "forge-config";

export function readSelectedConfig(): string {
  return localStorage.getItem(CONFIG_KEY) || "full_forge";
}

export function saveSelectedConfig(name: string): void {
  localStorage.setItem(CONFIG_KEY, name);
  window.dispatchEvent(new Event("forge-config"));
}
