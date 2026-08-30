import os
import uuid
from datetime import datetime

from fastapi import FastAPI, UploadFile, Form, HTTPException, BackgroundTasks
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
        hoy = datetime.utcnow().date()
        notas = (
            db.query(NotaCampo)
            .filter(NotaCampo.creado_en_dispositivo >= hoy)
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
