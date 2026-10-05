# Vigilante de stock Apple (Barcelona)

Avisa por Telegram cuando el **iPhone 18 Pro Max 512 GB Burdeos** (`MJXV4QL/A`) pasa a tener
stock de recogida en **Apple Passeig de Gràcia** o **Apple La Maquinista**.

```
GitHub Actions (cron 30 min) ─▶ turno de ~33 min ─▶ consulta Apple cada ~60 s
        ─▶ ¿sin stock → con stock? ─▶ Telegram + enlace de compra
        ─▶ state.json / history.csv (commit solo si cambia algo)
```

Sin dependencias: solo Python 3 y el endpoint de recogida de apple.com/es (el mismo que usa la web).
El patrón (Actions + estado versionado + concurrencia + Telegram por API directa) viene de `corolla_scrapper`.

## Puesta en marcha en GitHub (5 min)

1. Este repo debe ser **público**: así los minutos de Actions son ilimitados; en privado (2.000 min/mes gratis) no llega para consultar de forma continua.
   No hay secretos en el repo: `secretos.json` está en `.gitignore` y el token va como *secret*.
2. `Settings → Secrets and variables → Actions → New repository secret`:
   - `TELEGRAM_BOT_TOKEN` = token del bot (BotFather)
   - `TELEGRAM_CHAT_ID` = tu chat_id
3. **Diagnóstico**: pestaña *Actions → Vigilante stock iPhone → Run workflow* (minutos = 0).
   Debe llegarte a Telegram "🧪 Diagnóstico OK". Si llega "⚠️ no puede consultar a Apple", Apple está bloqueando las IPs de GitHub y esta vía no sirve (usa el PC o un servidor).
4. Listo: el cron hace el resto. Cada día sobre las 9:00 recibes un "✅ Vigilante activo".

## En tu PC (alternativa o respaldo)

Rellena `secretos.json` (`{"telegram_bot_token": "...", "telegram_chat_id": "..."}`) y ejecuta `iniciar_vigilante.bat`.
Comandos: `--once`, `--test-telegram`, `--chat-id`, `--loop MINUTOS`.

## Cómo evita falsos "sin stock"

Si Apple devuelve error, HTTP 4xx/5xx, algo que no es JSON o no devuelve las tiendas, **no** se cuenta como "sin stock":
espera, reintenta y, tras 3 fallos seguidos, te avisa una sola vez.

## Notas

- Solo avisa en la transición *sin stock → con stock* (no repite). `avisar_si_se_agota` en `config.json` activa el aviso contrario.
- `history.csv` guarda cada cambio de estado: sirve para ver cuándo repone Apple.
- GitHub desactiva los workflows programados de repos públicos tras 60 días sin actividad. Cuando compres el móvil, desactívalo (Actions → ⋯ → Disable workflow).
- Cambiar de color/capacidad: `config.json` (códigos en `codigos_iphone18promax.txt`).
