# Hotel AI · Sistema Multi-Agente para Hotelería

**Proyecto Intermedio 1 · Aplicaciones de AI a los Negocios · Universidad ORT Uruguay · 2026**
Autores: Facundo Bolani · Alan Bancic · Alan Schein

Demo en vivo: [facundobolani.com/hotelia/](https://facundobolani.com/hotelia/)

---

## ¿Qué es esto?

Un sistema multi-agente que automatiza el 90% de las interacciones operativas de un hotel mediano:
reservas, comunicación omnicanal, ciclo del huésped (pre/in/post-stay), upselling proactivo y
detección temprana de insatisfacción.

Cuatro agentes especializados con responsabilidad estricta y un orquestador central:

| Agente | Modelo | Dominio |
|---|---|---|
| Concierge | Claude Sonnet 4.6 | Clasifica intención y delega |
| Canal | Claude Haiku 4.5 | I/O omnicanal (web_chat, email) |
| Reservas | Claude Haiku 4.5 | Ciclo transaccional de reserva |
| Guest Lifecycle | Claude Sonnet 4.6 | Mensajes proactivos por fase |

## Estructura del repo

```
.
├── 00-arquitectura/        Spec maestra del sistema
├── 01-agente-concierge/    Spec del Concierge (incluye threat model)
├── 02-agente-canal/        Spec del Canal
├── 03-agente-reservas/     Spec de Reservas
├── 04-agente-guest-lifecycle/  Spec del Lifecycle
├── db/
│   ├── schema.sql          DDL Postgres (14 tablas, RLS, roles)
│   └── seeds.sql           Datos del hotel ficticio "Bahía Serena"
├── hotelai/                Paquete Python del backend
│   ├── schemas.py          Pydantic envelopes + enums
│   ├── state.py            LangGraph state
│   ├── settings.py         Config (pydantic-settings)
│   ├── db.py               Cliente Supabase
│   ├── server.py           FastAPI app entry
│   └── canal/              Agente Canal (Sprint 2)
├── web/                    Frontend del simulador (copia local)
├── pyproject.toml
├── requirements.txt        Para deploy en Render
├── render.yaml             Blueprint de Render
└── .env.example
```

## Arquitectura

```
Simulador (facundobolani.com/hotelia/)
        │ HTTPS · /api/web-chat/inbound
        ▼
Backend FastAPI (Render)
        │
        ▼
Agente Canal  →  Agente Concierge  →  Reservas o Lifecycle
                       │
                       ▼
              Supabase (estado compartido)
                       │
                       └─→ Anthropic API (Claude)
```

Ver `00-arquitectura/README.md` para el detalle (envelopes, threat model, RLS, etc.).

## Desarrollo local

```bash
# 1. Crear venv e instalar deps
python -m venv .venv
source .venv/bin/activate           # o .venv\Scripts\activate en Windows
pip install -r requirements.txt

# 2. Copiar y rellenar .env
cp .env.example .env
# Editar .env con ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

# 3. Aplicar SQL (solo primera vez)
# Pegar db/schema.sql y db/seeds.sql en Supabase Studio → SQL Editor

# 4. Levantar el server
uvicorn hotelai.server:app --reload --port 8000

# 5. Probar
curl http://localhost:8000/healthz
curl -X POST http://localhost:8000/api/web-chat/inbound \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"'$(uuidgen)'","channel":"web_chat","text":"¿Cuál es la clave del WiFi?"}'
```

## Deploy

El repo está conectado a Render via `render.yaml`. Cada push a `main` redeploya
automáticamente. Las claves secretas se setean en el dashboard de Render
(no en el archivo).

## Roadmap de sprints

| Sprint | Entrega | Estado |
|---|---|---|
| 1 | Fundaciones (schemas, SQL, state) | ✅ |
| 2 | Canal endpoint + persistencia + simulador | ✅ |
| 3 | Concierge real (Claude Sonnet 4.6) | ⏳ |
| 4 | Reservas (book/modify/cancel + flujo pago manual) | ⏳ |
| 5 | Lifecycle (scheduler + NPS + detección emocional) | ⏳ |
| 6 | Tests adversariales + endurecimiento | ⏳ |

## Decisiones de diseño clave

- **Separación estricta:** cada agente tiene un único dominio. *Si un agente puede
  hacer el trabajo de otro, el diseño está roto.*
- **Envelopes JSON validados:** todos los handoffs son contratos versionados con
  `extra="forbid"` y validators que rechazan canales/agentes fuera del scope.
- **Defensa por capas contra prompt injection:** texto del huésped siempre va
  envuelto en `<guest_message>` como datos, nunca como instrucciones. Output
  filter para bloquear PII, dominios externos y datos internos.
- **RLS en Supabase:** 29 policies que enforzan que cada agente solo escriba en
  su scope (`audit_log.agent_name` = su propio nombre).
- **Anti doble-booking en DB:** `EXCLUDE USING gist` sobre `(room_id, daterange)`
  hace físicamente imposible reservar dos veces el mismo cuarto solapado.

## Licencia

Proyecto académico. Código bajo MIT.
