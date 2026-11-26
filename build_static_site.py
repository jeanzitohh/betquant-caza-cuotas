import datetime as dt
import json
import os

from card_renderer import render_app_icon
from dashboard import HTML_PAGE
from providers import load_env

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "docs")

SW_JS = """const CACHE_NAME = 'caza-cuotas-v2';
const SHELL_URLS = ['./', './index.html', './manifest.webmanifest', './icon-192.png', './icon-512.png'];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(SHELL_URLS).catch(() => {})));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = event.request.url;
  if (!url.startsWith(self.location.origin)) return;
  event.respondWith(
    fetch(event.request)
      .then(resp => {
        if (resp && resp.status === 200) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(event.request, clone));
        }
        return resp;
      })
      .catch(() => caches.match(event.request))
  );
});

self.addEventListener('push', event => {
  let payload = { title: 'Caza Cuotas', body: 'Nuevo pronóstico o resultado disponible en el Canal.', url: './#canal' };
  try {
    if (event.data) payload = { ...payload, ...event.data.json() };
  } catch (e) {}
  event.waitUntil(
    self.registration.showNotification(payload.title || 'Caza Cuotas', {
      body: payload.body || '',
      icon: './icon-192.png',
      badge: './icon-192.png',
      tag: 'caza-cuotas-alert',
      renotify: true,
      data: { url: payload.url || './#canal' }
    })
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || './#canal';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const client of list) {
        if ('focus' in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
    })
  );
});
"""


def export_static_site(scan_res: dict | None = None, report_res: dict | None = None) -> str:
    """Export installable PWA bundle (docs/index.html, manifest.webmanifest, sw.js, icons, data.json)."""
    os.makedirs(DOCS_DIR, exist_ok=True)
    env = load_env()
    sb_url = env.get("SUPABASE_URL", "").strip()
    sb_anon = env.get("SUPABASE_ANON_KEY", "").strip()
    vapid_pub = env.get("VAPID_PUBLIC_KEY", "").strip()
    sb_ready = bool(sb_url and sb_anon)
    now_col = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)).strftime("%Y-%m-%d %H:%M")

    safe_scan = scan_res or {"matches": [], "parlays_a": []}
    safe_rep = report_res or {}

    if sb_ready:
        # Strict auth-only gate: never expose unauthenticated radar data in public static JSON
        payload = {"auth_required": True, "generated_col": now_col}
    else:
        payload = {
            "generated_col": now_col,
            "scan": safe_scan,
            "report": safe_rep,
        }
    with open(os.path.join(DOCS_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    # Copy local league logos into docs/logos/
    src_logos = os.path.join(BASE_DIR, "logos")
    dst_logos = os.path.join(DOCS_DIR, "logos")
    if os.path.isdir(src_logos):
        os.makedirs(dst_logos, exist_ok=True)
        for fn in os.listdir(src_logos):
            if fn.lower().endswith((".png", ".webp", ".svg")):
                with open(os.path.join(src_logos, fn), "rb") as rf, open(os.path.join(dst_logos, fn), "wb") as wf:
                    wf.write(rf.read())

    # PWA Icons & Manifest & Service Worker & Favicons
    for sz in (192, 512):
        with open(os.path.join(DOCS_DIR, f"icon-{sz}.png"), "wb") as f:
            f.write(render_app_icon(sz))

    # Also render 32x32 favicon
    with open(os.path.join(DOCS_DIR, "favicon-32.png"), "wb") as f:
        f.write(render_app_icon(32))
    with open(os.path.join(DOCS_DIR, "favicon.png"), "wb") as f:
        f.write(render_app_icon(32))

    # Copy favicon.svg and favicon.ico from root to docs if exist
    for fav_name in ("favicon.svg", "favicon.ico", "favicon-32.png"):
        src_f = os.path.join(BASE_DIR, fav_name)
        dst_f = os.path.join(DOCS_DIR, fav_name)
        if os.path.isfile(src_f) and not os.path.samefile(src_f, dst_f) if os.path.exists(dst_f) else os.path.isfile(src_f):
            try:
                with open(src_f, "rb") as rf, open(dst_f, "wb") as wf:
                    wf.write(rf.read())
            except Exception:
                pass

    manifest = {
        "name": "Caza Cuotas",
        "short_name": "Caza Cuotas",
        "description": "Pronósticos deportivos, cuotas y canal en vivo.",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": "#FAFBFD",
        "theme_color": "#7C3AED",
        "orientation": "portrait-primary",
        "icons": [
            {"src": "./icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "./icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    with open(os.path.join(DOCS_DIR, "manifest.webmanifest"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    with open(os.path.join(DOCS_DIR, "sw.js"), "w", encoding="utf-8") as f:
        f.write(SW_JS)

    static_html = HTML_PAGE.replace("const STATIC_MODE = false;", "const STATIC_MODE = true;")
    static_html = (
        static_html.replace("const SUPABASE_URL = '';", f"const SUPABASE_URL = {json.dumps(sb_url)};")
        .replace("const SUPABASE_ANON_KEY = '';", f"const SUPABASE_ANON_KEY = {json.dumps(sb_anon)};")
        .replace("const VAPID_PUBLIC_KEY = '';", f"const VAPID_PUBLIC_KEY = {json.dumps(vapid_pub)};")
    )
    pwa_head = (
        '  <link rel="manifest" href="./manifest.webmanifest" />\n'
        '  <link rel="apple-touch-icon" href="./icon-192.png" />\n'
        '  <meta name="theme-color" content="#7C3AED" />\n'
        '  <meta name="apple-mobile-web-app-capable" content="yes" />\n'
        '  <meta name="apple-mobile-web-app-status-bar-style" content="default" />\n'
    )
    if sb_ready:
        pwa_head += '  <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>\n'
    static_html = static_html.replace("</head>", pwa_head + "</head>")

    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(static_html)

    nojekyll = os.path.join(DOCS_DIR, ".nojekyll")
    if not os.path.exists(nojekyll):
        with open(nojekyll, "w", encoding="utf-8") as f:
            f.write("")

    return DOCS_DIR


if __name__ == "__main__":
    out = export_static_site()
    print(f"Static site exported successfully to {out}")

