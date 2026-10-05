# Vigilante de stock Apple (Barcelona)

Avisa por Telegram cuando el **iPhone 18 Pro Max 512 GB Burdeos** (`MJXV4QL/A`) pasa a tener
stock de recogida en **Apple Passeig de Gràcia** o **Apple La Maquinista**.

```
GitHub Actions (cron ~5 min) ─▶ una comprobación ligera (~15 s)
        ─▶ ¿sin stock → con stock? ─▶ Telegram + enlace de compra
        ─▶ state.json / history.csv (commit solo si cambia algo)
```

Sin dependencias: solo Python 3 y el endpoint de recogida de apple.com/es (el mismo que usa la web).
El patrón (Actions + estado versionado + concurrencia + Telegram por API directa) viene de `corolla_scrapper`.

## Puesta en marcha en GitHub (5 min)

1. Este repo debe ser **público**: así los minutos de Actions son gratuitos; en privado, ~288 ejecuciones al día (~8.600 min/mes) superan los 2.000 min/mes gratis.
   No hay secretos en el repo: `secretos.json` está en `.gitignore` y el token va como *secret*.
2. `Settings → Secrets and variables → Actions → New repository secret`:
   - `TELEGRAM_BOT_TOKEN` = token del bot (BotFather)
   - `TELEGRAM_CHAT_ID` = tu chat_id
3. **Diagnóstico**: pestaña *Actions → Vigilante stock iPhone → Run workflow*.
   Debe llegarte a Telegram "🧪 Diagnóstico OK". Si llega "⚠️ no puede consultar a Apple", Apple está bloqueando las IPs de GitHub y esta vía no sirve (usa el PC o un servidor).
4. Listo: el cron hace el resto. Cada día sobre las 9:00 recibes un "✅ Vigilante activo".

## Cadencia y límites (por qué cada ~5 min y no cada minuto)

- El cron de GitHub no baja de 5 min y suele retrasarse: la detección real es de **~5–15 min**.
- Se eligió una comprobación puntual y ligera (1 petición a Apple por pasada) y no un bucle 24/7: los términos de GitHub restringen
  usar Actions para actividad no relacionada con construir/probar/desplegar el proyecto y para cargas continuas desproporcionadas.
  Aun así, es un uso en zona gris: GitHub podría limitarlo. Úsalo con moderación y desactívalo cuando ya no haga falta.
- Apple puede limitar o bloquear temporalmente las consultas automatizadas (suele ser un HTTP 541/403 pasajero). Si pasa, el vigilante
  no lo toma por "sin stock" y te avisa tras 3 fallos seguidos. No usa cuentas ni compra nada.
- Los términos de uso de apple.com no se han revisado a fondo; el volumen es muy bajo (unas 288 consultas al día).
- Para reaccionar más rápido, usa el modo PC (`iniciar_vigilante.bat`, cada 120 s) mientras tu equipo esté encendido.

## En tu PC (alternativa o respaldo)

Rellena `secretos.json` (`{"telegram_bot_token": "...", "telegram_chat_id": "..."}`) y ejecuta `iniciar_vigilante.bat`.
Comandos: `--check` (una pasada), `--once`, `--test-telegram`, `--chat-id`, `--loop MINUTOS`.

## Cómo evita falsos "sin stock"

Si Apple devuelve error, HTTP 4xx/5xx, algo que no es JSON o no devuelve las tiendas, **no** se cuenta como "sin stock":
espera, reintenta y, tras 3 fallos seguidos, te avisa una sola vez.

## Notas

- Solo avisa en la transición *sin stock → con stock* (no repite). `avisar_si_se_agota` en `config.json` activa el aviso contrario.
- `history.csv` guarda cada cambio de estado: sirve para ver cuándo repone Apple.
- GitHub desactiva los workflows programados de repos públicos tras 60 días sin actividad. Cuando compres el móvil, desactívalo (Actions → ⋯ → Disable workflow).
- Cambiar de color/capacidad: `config.json` (códigos en `codigos_iphone18promax.txt`).
