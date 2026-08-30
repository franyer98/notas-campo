import os
import json
import httpx

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

PROMPT_SISTEMA = """Eres un asistente que convierte notas de voz dictadas en \
campo por un ingeniero de confiabilidad en inspecciones de emisiones \
fugitivas (cámara OGI) en Campo Rubiales, en un JSON estructurado.

Devuelve SOLO un objeto JSON, sin texto adicional, sin backticks, con estas \
claves:
- "cluster": string o null (número o nombre de clúster si se menciona)
- "componente": string o null (válvula, brida, conexión, tanque, etc.)
- "tipo_hallazgo": "fuga" | "anomalia" | "observacion" | "otro"
- "severidad": "baja" | "media" | "alta" | null
- "descripcion": resumen limpio y profesional de lo dictado, en español
- "accion_sugerida": string o null si el dictado menciona una acción a tomar
"""


async def estructurar_nota(texto: str) -> dict:
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 500,
        "system": PROMPT_SISTEMA,
        "messages": [{"role": "user", "content": texto}],
    }

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(ANTHROPIC_API_URL, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

    texto_respuesta = "".join(
        bloque["text"] for bloque in data["content"] if bloque["type"] == "text"
    )
    texto_limpio = texto_respuesta.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(texto_limpio)
    except json.JSONDecodeError:
        # Si el modelo no devolvió JSON válido, no perdemos la nota:
        # la guardamos cruda y la marcamos para revisión manual.
        return {"error_parseo": True, "texto_crudo": texto_respuesta}
