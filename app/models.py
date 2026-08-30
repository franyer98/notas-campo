import os
import uuid
from datetime import datetime

from sqlalchemy import create_engine, Column, String, DateTime, Text, JSON
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.environ["DATABASE_URL"]  # postgresql://user:pass@host/db

# pool_pre_ping y pool_recycle: mismo fix que usaste en reporte-cuadrillas
# para evitar conexiones muertas de Render/Postgres tras hibernación.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class NotaCampo(Base):
    __tablename__ = "notas_campo"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tasker_id = Column(String, unique=True, index=True, nullable=False)  # dedup, igual que MensajeProcesado
    usuario = Column(String, nullable=False)
    audio_path = Column(String, nullable=True)
    texto_offline = Column(Text, nullable=True)   # transcripción tosca hecha en el teléfono sin señal
    texto_whisper = Column(Text, nullable=True)   # transcripción fina hecha en el backend
    estructurada = Column(JSON, nullable=True)    # cluster, tipo, severidad, descripcion...
    estado = Column(String, default="pendiente")  # pendiente | transcrita | estructurada | error
    creado_en_dispositivo = Column(DateTime, nullable=False)  # timestamp real de campo, no de subida
    recibido_en = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "tasker_id": self.tasker_id,
            "usuario": self.usuario,
            "texto_offline": self.texto_offline,
            "texto_whisper": self.texto_whisper,
            "estructurada": self.estructurada,
            "estado": self.estado,
            "creado_en_dispositivo": self.creado_en_dispositivo.isoformat() if self.creado_en_dispositivo else None,
        }


def init_db():
    Base.metadata.create_all(engine)
