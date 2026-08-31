import os
import uuid
from datetime import datetime, timedelta

from fastapi import FastAPI, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import IntegrityError

from .models import SessionLocal, NotaCampo, init_db
from .transcribe import transcribir_audio
from .structure import estructurar_nota

app = FastAPI(title="Notas de Campo - Rubiales")

AUDIO_DIR = "/opt/render/project/src/audios"  # carpeta local dentro del contenedor.
# NOTA: en el plan gratis de Render el filesystem es efímero — estos audios
# se pierden en cada redeploy o cuando el servicio duerme por inactividad.
# El texto_offline queda igual como respaldo. Si más adelante necesitas
# conservar los audios permanentemente, hay que pasar a un plan con disco
# persistente y montar aquí ese disco (ej: /data).
os.makedirs(AUDIO_DIR, exist_ok=True)


@app.on_event("startup")
def startup():
    init_db()


async def procesar_nota(nota_id: str, audio_bytes: bytes | None):
    """Transcribe (si hay audio) y estructura la nota. Corre en background
    para que Tasker reciba el 200 OK de inmediato y no reintente por timeout."""
    db = SessionLocal()
    try:
        nota = db.query(NotaCampo).filter(NotaCampo.id == nota_id).first()
        if not nota:
            return

        texto_base = nota.texto_offline or ""

        if audio_bytes:
            try:
                texto_whisper = await transcribir_audio(audio_bytes)
                nota.texto_whisper = texto_whisper
                texto_base = texto_whisper  # el fino manda sobre el tosco offline
                nota.estado = "transcrita"
                db.commit()
            except Exception as e:
                nota.estado = f"error_transcripcion: {e}"
                db.commit()
                return

        if texto_base:
            try:
                nota.estructurada = await estructurar_nota(texto_base)
                nota.estado = "estructurada"
                db.commit()
            except Exception as e:
                nota.estado = f"error_estructuracion: {e}"
                db.commit()
    finally:
        db.close()


@app.post("/notas/upload")
async def subir_nota(
    background_tasks: BackgroundTasks,
    tasker_id: str = Form(...),          # ID único generado en el teléfono (dedup)
    usuario: str = Form(...),
    creado_en_dispositivo: str = Form(...),  # ISO 8601, hora real de campo
    texto_offline: str | None = Form(None),  # texto del reconocimiento offline de Android, si existe
    audio: UploadFile | None = None,
):
    db = SessionLocal()
    try:
        audio_bytes = None
        audio_path = None

        if audio is not None:
            audio_bytes = await audio.read()
            filename = f"{tasker_id}_{uuid.uuid4().hex[:8]}.ogg"
            audio_path = os.path.join(AUDIO_DIR, filename)
            with open(audio_path, "wb") as f:
                f.write(audio_bytes)

        nota = NotaCampo(
            id=str(uuid.uuid4()),
            tasker_id=tasker_id,
            usuario=usuario,
            audio_path=audio_path,
            texto_offline=texto_offline,
            creado_en_dispositivo=datetime.fromisoformat(creado_en_dispositivo),
            estado="pendiente",
        )
        db.add(nota)
        db.commit()
        db.refresh(nota)

    except IntegrityError:
        # tasker_id repetido -> Tasker ya reintentó una subida exitosa antes.
        # Igual que la dedup de MensajeProcesado en reporte-cuadrillas.
        db.rollback()
        return {"status": "duplicado_ignorado", "tasker_id": tasker_id}
    finally:
        db.close()

    background_tasks.add_task(procesar_nota, nota.id, audio_bytes)
    return {"status": "recibido", "id": nota.id}


@app.get("/notas/reporte")
def reporte_del_dia():
    db = SessionLocal()
    try:
        # Usamos las últimas 24 horas en vez de "medianoche UTC" para
        # evitar que el desfase entre la hora de Colombia (UTC-5) y UTC
        # haga que notas de "hoy" en Colombia parezcan de "ayer" aquí.
        desde = datetime.utcnow() - timedelta(hours=24)
        notas = (
            db.query(NotaCampo)
            .filter(NotaCampo.creado_en_dispositivo >= desde)
            .order_by(NotaCampo.creado_en_dispositivo)
            .all()
        )
        return [n.to_dict() for n in notas]
    finally:
        db.close()


@app.get("/notas/todas")
def todas_las_notas():
    """Sin filtro de fecha — útil para descartar desfases de zona horaria
    entre el dispositivo (Colombia, UTC-5) y el servidor (UTC)."""
    db = SessionLocal()
    try:
        notas = db.query(NotaCampo).order_by(NotaCampo.recibido_en.desc()).limit(50).all()
        return [n.to_dict() for n in notas]
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/notas/ver", response_class=HTMLResponse)
def ver_notas():
    """Vista visual de las notas — más fácil de leer en el navegador del
    teléfono que el JSON crudo de /notas/todas."""
    db = SessionLocal()
    try:
        notas = db.query(NotaCampo).order_by(NotaCampo.recibido_en.desc()).limit(50).all()
    finally:
        db.close()

    colores_severidad = {"alta": "#e74c3c", "media": "#f39c12", "baja": "#27ae60"}

    tarjetas = ""
    for n in notas:
        est = n.estructurada or {}
        cluster = est.get("cluster") or "—"
        componente = est.get("componente") or "—"
        tipo = est.get("tipo_hallazgo") or "—"
        severidad = est.get("severidad")
        descripcion = est.get("descripcion") or n.texto_whisper or n.texto_offline or "(sin texto)"
        accion = est.get("accion_sugerida")
        fecha = n.creado_en_dispositivo.strftime("%d/%m/%Y %I:%M %p") if n.creado_en_dispositivo else "—"

        color_sev = colores_severidad.get(severidad, "#555")
        badge_sev = f'<span style="background:{color_sev};color:#fff;padding:2px 10px;border-radius:12px;font-size:12px">{severidad or "sin definir"}</span>'

        badge_estado = ""
        if n.estado != "estructurada":
            badge_estado = f'<div style="color:#e74c3c;font-size:12px;margin-top:6px">⚠ {n.estado}</div>'

        accion_html = f'<div style="margin-top:8px;color:#8ab4f8;font-size:14px">➜ {accion}</div>' if accion else ""

        tarjetas += f"""
        <div style="background:#1e1e1e;border-radius:12px;padding:16px;margin-bottom:14px;border-left:4px solid {color_sev}">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                <span style="color:#aaa;font-size:13px">{fecha}</span>
                {badge_sev}
            </div>
            <div style="font-size:15px;color:#eee;line-height:1.4">{descripcion}</div>
            <div style="margin-top:10px;font-size:13px;color:#999">
                Clúster: <b style="color:#ddd">{cluster}</b> &nbsp;·&nbsp;
                Componente: <b style="color:#ddd">{componente}</b> &nbsp;·&nbsp;
                Tipo: <b style="color:#ddd">{tipo}</b>
            </div>
            {accion_html}
            {badge_estado}
        </div>
        """

    if not tarjetas:
        tarjetas = '<div style="color:#888;text-align:center;padding:40px">No hay notas todavía.</div>'

    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Notas de Campo</title>
        <style>
            body {{ background:#121212; margin:0; padding:16px; font-family: -apple-system, Roboto, sans-serif; }}
            h1 {{ color:#fff; font-size:20px; margin-bottom:16px; }}
        </style>
    </head>
    <body>
        <h1>📋 Notas de Campo — Rubiales</h1>
        {tarjetas}
    </body>
    </html>
    """
    return html
