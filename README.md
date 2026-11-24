# Bot de Apuestas Deportivas — Local, GitHub Actions (Nube Gratis) & Telegram

Proyecto en Python puro (sin dependencias externas) enfocado en **Liga BetPlay de Colombia (`col.1`)** y **Grandes Ligas Europeas** (`eng.1`, `esp.1`, `ita.1`, `ger.1`, `fra.1`, `uefa.champions`).

---

## 1. Cómo usarlo en tu PC (un clic)
Haz doble clic en `abrir_bot.bat` para abrir el panel visual (`BetQuant Monitor`) en `http://127.0.0.1:8055`.

---

## 2. Qué hace la nube gratis (GitHub Actions + GitHub Pages) y qué NO hace
- **Lo que SÍ hace 100% gratis (sin tarjeta):**
  - El workflow `.github/workflows/bot_cron.yml` se ejecuta automáticamente cada hora en los servidores de GitHub.
  - Liquida resultados terminados, escanea próximos partidos, actualiza la web pública en **GitHub Pages (`docs/`)** y **publica automáticamente al Canal de Telegram** (sin repetir partidos ya enviados).
- **Lo que NO hace GitHub Actions (aclaración honesta):**
  - GitHub Actions **no es un servidor socket prendido 24/7 escuchando mensajes en vivo**. Durante cada ejecución automática sí responde comandos que hayan llegado a la cola del bot, pero si necesitas un bot interactivo que conteste `/colombia` o `/apuestas` en 1 segundo a cualquier hora del día, debes dejar corriendo `python telegram_bot.py poll` en un servidor continuo (ej. VPS / Render / PC encendido).
  - En resumen: **para tu Canal de Telegram automático + Web pública en GitHub Pages funciona al 100% gratis en repo público**.

---

## 3. Cómo crear el Bot y el Canal de Telegram (3 minutos)
1. En Telegram busca a **@BotFather** y envía `/newbot`.
2. Ponle nombre (ej. `BetQuant Colombia`) y usuario terminado en `bot` (ej. `betquant_col_bot`).
3. Copia el **Token** que te da `@BotFather` (ejemplo: `123456789:AAH...`).
4. Crea un **Canal de Telegram** (ej. público `@betquant_colombia`).
5. Entra al Canal → **Administradores → Agregar administrador** → busca a tu bot y dale permiso para **Publicar mensajes**.
6. Anota el ID del canal: si es público es `@tu_canal` (si es privado empieza por `-100...`, puedes verlo reenviando un mensaje del canal a `@userinfobot`).

---

## 4. Cómo subirlo a GitHub (100% gratis en repo público)
1. Crea un repositorio **Público** en GitHub (en repos públicos GitHub Actions es ilimitado y GitHub Pages es gratis).
   > **Seguridad:** `.gitignore` ya bloquea `.env` para que tus claves privadas **nunca** se suban al repositorio.
2. Sube todos los archivos de esta carpeta (incluidos `.github/`, `docs/`, `paper_trades.db` y los `.py`).
3. En tu repositorio de GitHub ve a **Settings → Secrets and variables → Actions → New repository secret** y agrega:
   - `TELEGRAM_BOT_TOKEN`: el token de `@BotFather`
   - `TELEGRAM_CHANNEL_ID`: `@tu_canal` (o `-100...`)
   - `APIFOOTBALL_KEY` *(opcional)*: tu clave de API-Football
4. Activa la web pública en **Settings → Pages**:
   - Source: **Deploy from a branch**
   - Branch: **main** / carpeta **`/docs`** → Save.
5. Ve a la pestaña **Actions → Bot de Apuestas - Radar y Canal Telegram → Run workflow** para hacer la primera corrida de prueba y verificar que publique en tu Canal y actualice tu página web.

---

## 5. Comandos útiles locales
```powershell
# Probar todo el flujo en tu PC (liquidar, escanear, Telegram si está en .env, generar docs/)
python cloud_runner.py

# Dejar el bot escuchando comandos (/start, /colombia, /europa, /apuestas, /historial) 24/7 en tu PC/servidor
python telegram_bot.py poll

# Publicar una prueba al Canal de Telegram ahora
python telegram_bot.py test-channel
```
