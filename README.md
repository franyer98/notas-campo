# Notas de Campo — Rubiales

Backend para capturar notas de voz activadas por comando de voz, con cola
local para cuando no hay señal, y transcripción/estructuración automática.

## 1. Backend (Render)

1. Sube esta carpeta a un repo de GitHub.
2. En Render: **New > Web Service**, conecta el repo.
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Crea una base de datos Postgres en Render y copia su `DATABASE_URL`.
4. Añade un **disco persistente** (Render Disks) montado en `/data` — si no,
   los audios se pierden en cada redeploy/hibernación.
5. Variables de entorno (copia `.env.example`): `DATABASE_URL`,
   `GROQ_API_KEY` (crea cuenta gratis en console.groq.com), `ANTHROPIC_API_KEY`.
6. Igual que en reporte-cuadrillas, monta **UptimeRobot** apuntando a
   `/health` cada 5 min para evitar el cold-start cuando llegue una nota real.

## 2. Tasker + AutoVoice (en tu Android)

Esto es lo que da la activación "solo con la voz":

1. Instala **Tasker** y el plugin **AutoVoice** (Play Store).
2. **Perfil nuevo > Event > Plugin > AutoVoice > Recognized**.
   - Command Filter: `anota *` (el `*` captura lo que sigue).
   - Esto hace que Google Assistant/AutoVoice esté escuchando ese comando
     específico sin que tengas que abrir ninguna app.
3. **Tarea asociada** (se ejecuta cuando se detecta "anota..."):
   - **A1 — Variable Set**: `%TASKER_ID` = `%TIMES` + UUID simple (o usa la
     acción "UUID" de Tasker) — este es el `tasker_id` que dedupe en el backend.
   - **A2 — AutoVoice Record Audio** (o **Microphone** de Tasker): graba el
     audio hasta silencio, guarda en `/storage/emulated/0/NotasCampo/pendientes/%TASKER_ID.ogg`.
   - **A3 — Variable Set**: `%TEXTO_OFFLINE` = `%AVCOMMAND` (AutoVoice ya te
     da el texto reconocido por el motor de voz de Android, aunque sea offline).
   - **A4 — HTTP Request POST** a `https://tu-backend.onrender.com/notas/upload`:
     - form-data: `tasker_id`, `usuario=franyer`, `creado_en_dispositivo=%TIMES` (ISO),
       `texto_offline=%TEXTO_OFFLINE`, `audio=` (adjunta el archivo del paso A2).
     - **If Fail** (Tasker tiene una rama de error en HTTP Request): NO borres
       el archivo de `pendientes/`. Si tiene éxito, muévelo a `pendientes/enviados/`
       o bórralo.
   - **A5 — Flash/Notify**: "Nota guardada" o "Nota en cola (sin señal)" según
     el resultado del A4, para que sepas que sí se capturó.

4. **Perfil de sincronización** (tarea separada, corre cada 15 min o al
   detectar wifi/datos):
   - Lista archivos en `pendientes/`.
   - Por cada uno, repite el POST del paso A4 con su `tasker_id` original
     (el backend ya deduplica si alguno sí se había enviado a medias).

## 3. Por qué esta estructura

- **Nunca se pierde una nota**: se escribe a disco local (A2) antes de
  intentar cualquier red.
- **Dedup por `tasker_id`**: si Tasker reintenta una subida que en realidad
  sí llegó, el backend la ignora en vez de duplicarla (constraint `unique`
  en `models.py`).
- **Doble transcripción**: `texto_offline` (tosco, inmediato, de Android) +
  `texto_whisper` (fino, del backend) — si Whisper falla, igual te queda el
  texto offline como respaldo.
- **Procesamiento en background** (`BackgroundTasks` en `main.py`): Tasker
  recibe el 200 OK al instante, no espera a que termine la transcripción —
  importante con señal débil donde un timeout largo haría que Tasker
  reintente innecesariamente.

## 4. Consultar el reporte del día

`GET /notas/reporte` devuelve el JSON de todas las notas de hoy, ya
estructuradas (cluster, componente, tipo de hallazgo, severidad). Puedes
conectar esto directo a reporte-emisiones-cpf más adelante.
