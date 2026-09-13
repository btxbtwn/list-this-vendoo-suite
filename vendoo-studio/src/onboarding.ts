const SETUP_GUIDE_KEY = "vendoo-studio.setup-guide";

export function isSetupGuideDismissed(): boolean {
  try {
    return localStorage.getItem(SETUP_GUIDE_KEY) === "done";
  } catch {
    return false;
  }
}

export function dismissSetupGuide(): void {
  try {
    localStorage.setItem(SETUP_GUIDE_KEY, "done");
  } catch {
    /* ignore quota / private-mode failures */
  }
}
