/**
 * Fire-and-forget transient hint (bottom-centre toast).
 *
 * Deliberately implemented outside React: the callers are keyboard handlers
 * that must not trigger a re-render of the whole editor, and the hint must
 * never steal focus or pointer events from the canvas.
 */
let host: HTMLDivElement | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;

const ensureHost = (): HTMLDivElement => {
  if (host && document.body.contains(host)) return host;
  host = document.createElement('div');
  host.setAttribute('data-transient-hint', '');
  host.style.cssText = [
    'position:fixed',
    'left:50%',
    'bottom:120px',
    'transform:translateX(-50%)',
    'padding:6px 14px',
    'border-radius:9999px',
    'background:rgba(15,23,42,0.92)',
    'border:1px solid rgba(148,163,184,0.35)',
    'color:#e2e8f0',
    'font-size:12px',
    'font-weight:500',
    'letter-spacing:0.02em',
    'pointer-events:none',
    'z-index:9999',
    'opacity:0',
    'transition:opacity 160ms ease',
    'white-space:nowrap',
  ].join(';');
  document.body.appendChild(host);
  return host;
};

export function showTransientHint(message: string, durationMs = 2000): void {
  const el = ensureHost();
  el.textContent = message;
  el.style.opacity = '1';
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    el.style.opacity = '0';
  }, durationMs);
}
