-- =============================================================================
-- HOTEL AI · DDL Postgres / Supabase
-- =============================================================================
-- Proyecto Intermedio 1 · Universidad ORT Uruguay · 2026
--
-- Convenciones:
--   · UUID v4 como PK por defecto.
--   · snake_case en tablas y columnas.
--   · created_at / updated_at en TIMESTAMPTZ (UTC).
--   · ENUMs nativos de Postgres mirror Python enums en hotelai/schemas.py.
--   · RLS habilitada en tablas con datos sensibles. service_role bypassea RLS.
--
-- Aplicación:
--   psql "$DATABASE_URL" -f db/schema.sql
--   psql "$DATABASE_URL" -f db/seeds.sql
--
-- IDEMPOTENCIA:
--   Se usa DROP ... CASCADE al inicio para que re-correr el script desde cero
--   sea seguro. En producción esto se reemplaza por migrations versionadas.
-- =============================================================================

-- =============================================================================
-- 0. EXTENSIONS
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "btree_gist";  -- exclusión por rango (room booking)
CREATE EXTENSION IF NOT EXISTS "citext";      -- email case-insensitive

-- =============================================================================
-- 1. LIMPIEZA (orden inverso a dependencias)
-- =============================================================================
DROP TABLE IF EXISTS nps_responses          CASCADE;
DROP TABLE IF EXISTS payment_confirmations  CASCADE;
DROP TABLE IF EXISTS escalations            CASCADE;
DROP TABLE IF EXISTS audit_log              CASCADE;
DROP TABLE IF EXISTS messages               CASCADE;
DROP TABLE IF EXISTS conversations          CASCADE;
DROP TABLE IF EXISTS reservations           CASCADE;
DROP TABLE IF EXISTS upsell_catalog         CASCADE;
DROP TABLE IF EXISTS static_facts           CASCADE;
DROP TABLE IF EXISTS policies               CASCADE;
DROP TABLE IF EXISTS rates                  CASCADE;
DROP TABLE IF EXISTS rooms                  CASCADE;
DROP TABLE IF EXISTS room_categories        CASCADE;
DROP TABLE IF EXISTS guests                 CASCADE;

DROP TYPE IF EXISTS channel_enum            CASCADE;
DROP TYPE IF EXISTS conversation_state_enum CASCADE;
DROP TYPE IF EXISTS guest_phase_enum        CASCADE;
DROP TYPE IF EXISTS reservation_status_enum CASCADE;
DROP TYPE IF EXISTS payment_status_enum     CASCADE;
DROP TYPE IF EXISTS reservation_source_enum CASCADE;
DROP TYPE IF EXISTS agent_name_enum         CASCADE;
DROP TYPE IF EXISTS escalation_severity_enum CASCADE;
DROP TYPE IF EXISTS escalation_status_enum  CASCADE;
DROP TYPE IF EXISTS message_direction_enum  CASCADE;
DROP TYPE IF EXISTS message_role_enum       CASCADE;

-- =============================================================================
-- 2. ENUMS  (mirror de hotelai/schemas.py)
-- =============================================================================
CREATE TYPE channel_enum            AS ENUM ('web_chat', 'email', 'whatsapp', 'sms', 'voice');
CREATE TYPE conversation_state_enum AS ENUM ('active', 'awaiting_payment', 'escalated_human', 'closed');
CREATE TYPE guest_phase_enum        AS ENUM ('none', 'pre_stay', 'in_stay', 'post_stay');
CREATE TYPE reservation_status_enum AS ENUM ('pending_payment', 'confirmed', 'checked_in', 'checked_out', 'cancelled', 'no_show');
CREATE TYPE payment_status_enum     AS ENUM ('pending', 'paid', 'refunded', 'partial_refund');
CREATE TYPE reservation_source_enum AS ENUM ('direct', 'booking', 'expedia', 'airbnb');
CREATE TYPE agent_name_enum         AS ENUM ('concierge', 'canal', 'reservas', 'lifecycle', 'human', 'system');
CREATE TYPE escalation_severity_enum AS ENUM ('low', 'med', 'high', 'critical');
CREATE TYPE escalation_status_enum  AS ENUM ('open', 'in_progress', 'resolved');
CREATE TYPE message_direction_enum  AS ENUM ('inbound', 'outbound');
CREATE TYPE message_role_enum       AS ENUM ('guest', 'agent', 'system', 'human_staff');

-- =============================================================================
-- 3. HELPERS
-- =============================================================================
-- Trigger genérico para mantener updated_at.
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- 4. TABLAS DE CATÁLOGO (poco/no cambian, mayormente seed)
-- =============================================================================

-- room_categories: tipos de habitación
CREATE TABLE room_categories (
  category_id    TEXT PRIMARY KEY,                        -- 'single', 'double', etc.
  display_name   TEXT NOT NULL,
  capacity_adults SMALLINT NOT NULL CHECK (capacity_adults BETWEEN 1 AND 6),
  capacity_children SMALLINT NOT NULL DEFAULT 0,
  description    TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_room_categories_touch BEFORE UPDATE ON room_categories
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- rooms: habitaciones físicas
CREATE TABLE rooms (
  room_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  room_number    TEXT NOT NULL UNIQUE,                    -- '101', '201', '301'
  category_id    TEXT NOT NULL REFERENCES room_categories(category_id),
  floor          SMALLINT,
  active         BOOLEAN NOT NULL DEFAULT TRUE,           -- false si está en mantenimiento prolongado
  notes          TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_rooms_category ON rooms(category_id);
CREATE INDEX idx_rooms_active   ON rooms(active) WHERE active = TRUE;
CREATE TRIGGER trg_rooms_touch BEFORE UPDATE ON rooms
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- rates: tarifa por categoría (sin temporadas en MVP)
CREATE TABLE rates (
  rate_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  category_id    TEXT NOT NULL REFERENCES room_categories(category_id),
  price_usd      NUMERIC(10,2) NOT NULL CHECK (price_usd >= 0),
  effective_from DATE NOT NULL DEFAULT '2026-01-01',
  effective_to   DATE NOT NULL DEFAULT '2099-12-31',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT rates_date_order CHECK (effective_from < effective_to)
);
CREATE INDEX idx_rates_category_effective ON rates(category_id, effective_from, effective_to);

-- policies: políticas del hotel (key/value) que el agente Reservas consulta
CREATE TABLE policies (
  policy_key     TEXT PRIMARY KEY,
  value          JSONB NOT NULL,
  description    TEXT,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_policies_touch BEFORE UPDATE ON policies
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- static_facts: respuestas pre-aprobadas que el Concierge puede dar directo
-- (WiFi, dirección, horarios). Multi-idioma vía sub-key.
CREATE TABLE static_facts (
  fact_key       TEXT PRIMARY KEY,                        -- 'wifi_password', 'hotel_address'
  values_by_lang JSONB NOT NULL,                          -- {"es":"...", "en":"..."}
  description    TEXT,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_static_facts_touch BEFORE UPDATE ON static_facts
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- upsell_catalog: productos ofrecibles por el Lifecycle
CREATE TABLE upsell_catalog (
  upsell_id      TEXT PRIMARY KEY,                        -- 'late_checkout', 'spa_60min'
  display_name_es TEXT NOT NULL,
  display_name_en TEXT,
  description    TEXT,
  price_usd      NUMERIC(10,2) NOT NULL CHECK (price_usd >= 0),
  available_in_phase guest_phase_enum NOT NULL DEFAULT 'pre_stay',
  active         BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_upsell_catalog_touch BEFORE UPDATE ON upsell_catalog
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- =============================================================================
-- 5. TABLAS DE NEGOCIO
-- =============================================================================

-- guests: perfil del huésped (único por identificador)
CREATE TABLE guests (
  guest_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  full_name         TEXT,
  email             CITEXT,                                       -- case-insensitive
  phone             TEXT,                                         -- E.164 normalizado
  document_id       TEXT,                                         -- CI/DNI/passport (PII sensible)
  language_pref     CHAR(2) NOT NULL DEFAULT 'es',
  vip_flag          BOOLEAN NOT NULL DEFAULT FALSE,
  consent_marketing BOOLEAN NOT NULL DEFAULT FALSE,
  consent_updated_at TIMESTAMPTZ,
  notes             TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Al menos uno de email/phone debe estar (sino no podemos identificar al huésped)
  CONSTRAINT guests_needs_identifier CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_guests_email_unique ON guests(LOWER(email)) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_guests_phone_unique ON guests(phone) WHERE phone IS NOT NULL;
CREATE INDEX idx_guests_vip ON guests(vip_flag) WHERE vip_flag = TRUE;
CREATE TRIGGER trg_guests_touch BEFORE UPDATE ON guests
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- reservations: ciclo completo de una reserva
CREATE TABLE reservations (
  reservation_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  guest_id        UUID NOT NULL REFERENCES guests(guest_id) ON DELETE RESTRICT,
  room_id         UUID NOT NULL REFERENCES rooms(room_id) ON DELETE RESTRICT,
  check_in        DATE NOT NULL,
  check_out       DATE NOT NULL,
  status          reservation_status_enum NOT NULL DEFAULT 'pending_payment',
  payment_status  payment_status_enum NOT NULL DEFAULT 'pending',
  total_amount_usd NUMERIC(10,2) NOT NULL CHECK (total_amount_usd >= 0),
  source          reservation_source_enum NOT NULL DEFAULT 'direct',
  n_adults        SMALLINT NOT NULL DEFAULT 1 CHECK (n_adults >= 1),
  n_children      SMALLINT NOT NULL DEFAULT 0 CHECK (n_children >= 0),
  notes           TEXT,
  -- Para el flujo de pago manual: hasta cuándo se mantiene bloqueada la room
  payment_hold_until TIMESTAMPTZ,
  -- Trazabilidad
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  cancelled_at    TIMESTAMPTZ,

  CONSTRAINT reservations_date_order CHECK (check_in < check_out),
  -- check_in no puede ser en el pasado al crear (validación adicional en app)
  CONSTRAINT reservations_dates_reasonable CHECK (check_out <= check_in + INTERVAL '365 days')
);

-- Índice de exclusión: NO se puede tener dos reservas activas (no canceladas)
-- en la misma habitación con rangos de fechas solapados.
-- Reservas en pending_payment también ocupan slot (durante el TTL).
ALTER TABLE reservations
  ADD CONSTRAINT reservations_no_overlap
  EXCLUDE USING gist (
    room_id WITH =,
    daterange(check_in, check_out, '[)') WITH &&
  )
  WHERE (status IN ('pending_payment', 'confirmed', 'checked_in'));

CREATE INDEX idx_reservations_guest ON reservations(guest_id);
CREATE INDEX idx_reservations_room  ON reservations(room_id);
CREATE INDEX idx_reservations_status ON reservations(status);
CREATE INDEX idx_reservations_checkin ON reservations(check_in);
CREATE INDEX idx_reservations_pending_hold ON reservations(payment_hold_until)
  WHERE status = 'pending_payment';
CREATE TRIGGER trg_reservations_touch BEFORE UPDATE ON reservations
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- conversations: una por (guest_id, channel) activa
CREATE TABLE conversations (
  conversation_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  guest_id         UUID REFERENCES guests(guest_id) ON DELETE SET NULL,
  -- Identificador externo del canal (phone E.164 o email) para resolver primer contacto.
  external_identifier TEXT NOT NULL,
  channel          channel_enum NOT NULL,
  state            conversation_state_enum NOT NULL DEFAULT 'active',
  current_phase    guest_phase_enum NOT NULL DEFAULT 'none',
  last_agent       agent_name_enum,
  -- reserva asociada activa, si hay (acelera lookup del Lifecycle)
  active_reservation_id UUID REFERENCES reservations(reservation_id) ON DELETE SET NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  closed_at        TIMESTAMPTZ
);
CREATE UNIQUE INDEX idx_conversations_active_per_channel
  ON conversations(external_identifier, channel)
  WHERE state IN ('active', 'awaiting_payment', 'escalated_human');
CREATE INDEX idx_conversations_guest ON conversations(guest_id);
CREATE INDEX idx_conversations_state ON conversations(state);
CREATE TRIGGER trg_conversations_touch BEFORE UPDATE ON conversations
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- messages: cada mensaje en cada conversación
CREATE TABLE messages (
  message_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  conversation_id  UUID NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
  trace_id         UUID NOT NULL,
  direction        message_direction_enum NOT NULL,
  role             message_role_enum NOT NULL,
  agent_name       agent_name_enum,
  content          TEXT NOT NULL,
  raw_payload      JSONB,                                  -- payload original del canal
  classification   JSONB,                                  -- intent, confidence, flags
  -- Idempotencia: si llega el mismo channel_msg_id 2x, NO duplicar
  channel_msg_id   TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_messages_conversation_time ON messages(conversation_id, created_at DESC);
CREATE INDEX idx_messages_trace ON messages(trace_id);
CREATE UNIQUE INDEX idx_messages_channel_msg_id_unique
  ON messages(conversation_id, channel_msg_id)
  WHERE channel_msg_id IS NOT NULL;

-- audit_log: todo lo que hace cada agente
CREATE TABLE audit_log (
  log_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  trace_id         UUID NOT NULL,
  conversation_id  UUID REFERENCES conversations(conversation_id) ON DELETE SET NULL,
  agent_name       agent_name_enum NOT NULL,
  action           TEXT NOT NULL,                          -- 'tool_call', 'delegation', 'refusal', etc.
  payload_hash     TEXT,
  result_hash      TEXT,
  payload          JSONB,                                  -- truncado y sanitizado
  result           JSONB,
  duration_ms      INTEGER,
  tokens_in        INTEGER,
  tokens_out       INTEGER,
  cost_usd         NUMERIC(10,6),
  error            TEXT,
  prompt_version   TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_log_trace ON audit_log(trace_id);
CREATE INDEX idx_audit_log_conversation ON audit_log(conversation_id);
CREATE INDEX idx_audit_log_agent_time ON audit_log(agent_name, created_at DESC);
CREATE INDEX idx_audit_log_action ON audit_log(action);

-- escalations: cuando un caso pasa a humano
CREATE TABLE escalations (
  escalation_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  conversation_id  UUID NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
  triggered_by_agent agent_name_enum NOT NULL,
  reason_code      TEXT NOT NULL,
  severity         escalation_severity_enum NOT NULL,
  reason_detail    JSONB,
  assigned_to      TEXT,                                   -- staff_id / email
  status           escalation_status_enum NOT NULL DEFAULT 'open',
  sla_due_at       TIMESTAMPTZ NOT NULL,
  resolution_notes TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at      TIMESTAMPTZ
);
CREATE INDEX idx_escalations_status ON escalations(status);
CREATE INDEX idx_escalations_sla ON escalations(sla_due_at) WHERE status != 'resolved';
CREATE INDEX idx_escalations_conversation ON escalations(conversation_id);

-- payment_confirmations: log del flujo manual "ya pagué" (MVP, sin gateway)
CREATE TABLE payment_confirmations (
  confirmation_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  reservation_id   UUID NOT NULL REFERENCES reservations(reservation_id) ON DELETE CASCADE,
  conversation_id  UUID REFERENCES conversations(conversation_id) ON DELETE SET NULL,
  -- Acción del huésped: 'claimed_paid' (dijo que sí) o 'denied' (dijo que no)
  guest_response   TEXT NOT NULL CHECK (guest_response IN ('claimed_paid', 'denied', 'no_response')),
  reminder_number  SMALLINT NOT NULL DEFAULT 0,
  notes            TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_payment_conf_reservation ON payment_confirmations(reservation_id);

-- nps_responses: respuestas del Lifecycle post-stay
CREATE TABLE nps_responses (
  nps_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  reservation_id   UUID NOT NULL UNIQUE REFERENCES reservations(reservation_id) ON DELETE CASCADE,
  guest_id         UUID NOT NULL REFERENCES guests(guest_id) ON DELETE CASCADE,
  score            SMALLINT NOT NULL CHECK (score BETWEEN 0 AND 10),
  free_text        TEXT,
  themes           JSONB,                                  -- temas extraídos por Sonnet
  review_requested BOOLEAN NOT NULL DEFAULT FALSE,         -- True si pedimos review pública
  review_requested_at TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_nps_guest ON nps_responses(guest_id);
CREATE INDEX idx_nps_score ON nps_responses(score);

-- =============================================================================
-- 6. ROLES (uno por agente, todos NOLOGIN — heredan al rol de aplicación)
-- =============================================================================
-- En Supabase, los agentes corren bajo `service_role` (que bypassea RLS).
-- Estos roles documentan la INTENCIÓN de permisos. Para enforcement real:
--   · usar JWT claim 'agent' y RLS con auth.jwt(), o
--   · cada agente se conecta con su propio user/pwd.
-- En el MVP usamos service_role + checks en aplicación (los tools validan).
-- =============================================================================
DO $$ BEGIN CREATE ROLE role_concierge NOINHERIT NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE role_canal     NOINHERIT NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE role_reservas  NOINHERIT NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE role_lifecycle NOINHERIT NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE role_staff     NOINHERIT NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- =============================================================================
-- 7. GRANTS por rol (mínimos privilegios)
-- =============================================================================

-- ── Catálogo de lectura para todos los agentes ──
GRANT SELECT ON room_categories, rooms, rates, policies, static_facts, upsell_catalog
  TO role_concierge, role_canal, role_reservas, role_lifecycle, role_staff;

-- ── role_concierge ──
GRANT SELECT                    ON guests, reservations, messages           TO role_concierge;
GRANT SELECT, INSERT, UPDATE    ON conversations, audit_log, escalations    TO role_concierge;

-- ── role_canal ──
GRANT SELECT                    ON guests                                   TO role_canal;
GRANT SELECT, INSERT, UPDATE    ON conversations, messages, audit_log       TO role_canal;

-- ── role_reservas ──
GRANT SELECT                    ON guests                                   TO role_reservas;
GRANT SELECT, INSERT, UPDATE    ON reservations, audit_log, payment_confirmations
                                                                            TO role_reservas;

-- ── role_lifecycle ──
GRANT SELECT                    ON guests, reservations                     TO role_lifecycle;
GRANT SELECT, INSERT, UPDATE    ON audit_log, escalations, nps_responses    TO role_lifecycle;
-- También puede insertar mensajes salientes (proactivos)
GRANT SELECT, INSERT            ON messages                                 TO role_lifecycle;

-- ── role_staff (humano) ──  acceso amplio para resolver escalations
GRANT SELECT, INSERT, UPDATE    ON guests, reservations, conversations,
                                  messages, audit_log, escalations,
                                  nps_responses, payment_confirmations      TO role_staff;

-- =============================================================================
-- 8. RLS (defensa en profundidad — incluso si un agente usa una conexión
--    distinta, no puede leer datos fuera de su scope)
-- =============================================================================

ALTER TABLE guests        ENABLE ROW LEVEL SECURITY;
ALTER TABLE reservations  ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages      ENABLE ROW LEVEL SECURITY;
ALTER TABLE escalations   ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log     ENABLE ROW LEVEL SECURITY;
ALTER TABLE nps_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_confirmations ENABLE ROW LEVEL SECURITY;

-- Política universal: staff puede todo en sus tablas (define ALL_ROW para roles humanos)
CREATE POLICY staff_all_guests        ON guests        FOR ALL TO role_staff USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY staff_all_reservations  ON reservations  FOR ALL TO role_staff USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY staff_all_conversations ON conversations FOR ALL TO role_staff USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY staff_all_messages      ON messages      FOR ALL TO role_staff USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY staff_all_escalations   ON escalations   FOR ALL TO role_staff USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY staff_all_audit         ON audit_log     FOR ALL TO role_staff USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY staff_all_nps           ON nps_responses FOR ALL TO role_staff USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY staff_all_payment_conf  ON payment_confirmations FOR ALL TO role_staff USING (TRUE) WITH CHECK (TRUE);

-- Concierge: SELECT en guests y reservations (de cualquiera, necesita lookup)
CREATE POLICY concierge_select_guests       ON guests        FOR SELECT TO role_concierge USING (TRUE);
CREATE POLICY concierge_select_reservations ON reservations  FOR SELECT TO role_concierge USING (TRUE);
CREATE POLICY concierge_select_messages     ON messages      FOR SELECT TO role_concierge USING (TRUE);
CREATE POLICY concierge_rw_conversations    ON conversations FOR ALL    TO role_concierge USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY concierge_insert_audit        ON audit_log     FOR INSERT TO role_concierge WITH CHECK (agent_name = 'concierge');
CREATE POLICY concierge_select_audit        ON audit_log     FOR SELECT TO role_concierge USING (agent_name = 'concierge');
CREATE POLICY concierge_rw_escalations      ON escalations   FOR ALL    TO role_concierge USING (TRUE) WITH CHECK (TRUE);

-- Canal: NO ve guests, solo lookup por identifier (controlado en app).
CREATE POLICY canal_rw_conversations ON conversations FOR ALL    TO role_canal USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY canal_rw_messages      ON messages      FOR ALL    TO role_canal USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY canal_insert_audit     ON audit_log     FOR INSERT TO role_canal WITH CHECK (agent_name = 'canal');

-- Reservas: solo opera sobre reservations cuya guest_id matchee el envelope (enforce en app).
CREATE POLICY reservas_select_guests    ON guests       FOR SELECT TO role_reservas USING (TRUE);
CREATE POLICY reservas_rw_reservations  ON reservations FOR ALL    TO role_reservas USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY reservas_insert_audit     ON audit_log    FOR INSERT TO role_reservas WITH CHECK (agent_name = 'reservas');
CREATE POLICY reservas_rw_payment_conf  ON payment_confirmations FOR ALL TO role_reservas USING (TRUE) WITH CHECK (TRUE);

-- Lifecycle: lectura amplia, escritura limitada (mensajes salientes + nps + escalations).
CREATE POLICY lifecycle_select_guests       ON guests        FOR SELECT TO role_lifecycle USING (TRUE);
CREATE POLICY lifecycle_select_reservations ON reservations  FOR SELECT TO role_lifecycle USING (TRUE);
CREATE POLICY lifecycle_insert_messages     ON messages      FOR INSERT TO role_lifecycle WITH CHECK (direction = 'outbound');
CREATE POLICY lifecycle_select_messages     ON messages      FOR SELECT TO role_lifecycle USING (TRUE);
CREATE POLICY lifecycle_insert_audit        ON audit_log     FOR INSERT TO role_lifecycle WITH CHECK (agent_name = 'lifecycle');
CREATE POLICY lifecycle_rw_escalations      ON escalations   FOR ALL    TO role_lifecycle USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY lifecycle_rw_nps              ON nps_responses FOR ALL    TO role_lifecycle USING (TRUE) WITH CHECK (TRUE);

-- =============================================================================
-- 9. VIEWS útiles
-- =============================================================================

-- Disponibilidad rápida: una fila por habitación por día (próximos 30 días).
-- Útil para el agente Reservas. Para producción usar vista materializada + refresh.
CREATE OR REPLACE VIEW v_room_availability AS
SELECT
  r.room_id,
  r.room_number,
  r.category_id,
  d.day::date AS day,
  CASE
    WHEN res.reservation_id IS NULL THEN 'available'
    ELSE res.status::text
  END AS day_status
FROM rooms r
CROSS JOIN generate_series(CURRENT_DATE, CURRENT_DATE + INTERVAL '30 days', INTERVAL '1 day') AS d(day)
LEFT JOIN reservations res
  ON res.room_id = r.room_id
  AND res.status IN ('pending_payment', 'confirmed', 'checked_in')
  AND d.day::date >= res.check_in
  AND d.day::date <  res.check_out
WHERE r.active = TRUE;

-- Conversaciones que deberían cerrarse por inactividad (>24h sin movimiento).
CREATE OR REPLACE VIEW v_stale_conversations AS
SELECT c.*
FROM conversations c
WHERE c.state IN ('active', 'awaiting_payment')
  AND c.updated_at < NOW() - INTERVAL '24 hours';

-- =============================================================================
-- 10. COMENTARIOS DOCUMENTALES
-- =============================================================================
COMMENT ON TABLE guests        IS 'Perfil único del huésped. PII sensible: email, phone, document_id.';
COMMENT ON TABLE reservations  IS 'Ciclo de reserva. EXCLUDE constraint impide doble booking del mismo cuarto.';
COMMENT ON TABLE conversations IS 'Una conversación activa por (external_identifier, channel).';
COMMENT ON TABLE audit_log     IS 'Append-only. Cada acción de cada agente queda registrada.';
COMMENT ON TABLE escalations   IS 'Casos transferidos a humano. SLA por severity.';
COMMENT ON TABLE payment_confirmations IS 'MVP: registro del flujo manual "ya pagaste?" sin gateway real.';

COMMENT ON COLUMN reservations.payment_hold_until IS 'TTL del bloqueo de la habitación mientras la reserva está en pending_payment.';
COMMENT ON COLUMN messages.channel_msg_id IS 'Idempotencia: si el provider reenvía, no duplicamos.';

-- =============================================================================
-- FIN
-- =============================================================================
