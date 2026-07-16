const CHUNK_RELOAD_MARKER = "fquiz:chunk-reload:pending";
const CHUNK_RELOAD_COOLDOWN_MS = 2 * 60 * 1000;

const CHUNK_ERROR_PATTERNS = [
  /ChunkLoadError/i,
  /Loading chunk [\d]+ failed/i,
  /Loading CSS chunk [\d]+ failed/i,
  /Failed to fetch dynamically imported module/i,
  /Importing a module script failed/i,
  /dynamically imported module/i,
];

function stringifyError(error: unknown): string {
  if (error instanceof Error) {
    return `${error.name}: ${error.message}`;
  }
  if (typeof error === "string") {
    return error;
  }
  if (error && typeof error === "object") {
    if ("message" in error && typeof (error as { message?: unknown }).message === "string") {
      return (error as { message: string }).message;
    }
    return String(error);
  }
  return "";
}

export function isChunkLoadError(error: unknown): boolean {
  const message = stringifyError(error);
  if (!message) {
    return false;
  }
  return CHUNK_ERROR_PATTERNS.some((pattern) => pattern.test(message));
}

export function reloadOnceOnChunkError(error: unknown): boolean {
  if (typeof window === "undefined" || !isChunkLoadError(error)) {
    return false;
  }

  try {
    const now = Date.now();
    const lastReloadAtText = window.sessionStorage.getItem(CHUNK_RELOAD_MARKER);
    const lastReloadAt = lastReloadAtText ? Number(lastReloadAtText) : 0;

    if (
      Number.isFinite(lastReloadAt)
      && lastReloadAt > 0
      && now - lastReloadAt < CHUNK_RELOAD_COOLDOWN_MS
    ) {
      return false;
    }
    window.sessionStorage.setItem(CHUNK_RELOAD_MARKER, String(now));
  } catch {
    // Best-effort marker only.
  }

  window.location.reload();
  return true;
}
