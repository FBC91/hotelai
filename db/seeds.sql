-- =============================================================================
-- HOTEL AI · SEEDS (datos inventados del hotel ficticio)
-- =============================================================================
-- Hotel ficticio: "Hotel Bahía Serena" · Punta del Este, Uruguay.
-- Correr DESPUÉS de schema.sql:
--   psql "$DATABASE_URL" -f db/seeds.sql
--
-- Re-correr es seguro: usa ON CONFLICT DO NOTHING / DO UPDATE donde aplica.
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. CATÁLOGO DE CATEGORÍAS DE HABITACIÓN
-- =============================================================================
INSERT INTO room_categories (category_id, display_name, capacity_adults, capacity_children, description)
VALUES
  ('single',       'Single',        1, 0, 'Habitación individual con cama 1 plaza. Vista interior.'),
  ('double',       'Double',        2, 1, 'Habitación doble con cama matrimonial. Vista parcial al mar.'),
  ('twin',         'Twin',          2, 1, 'Habitación con dos camas individuales. Vista parcial al mar.'),
  ('junior_suite', 'Junior Suite',  2, 2, 'Suite junior con sala de estar separada y vista al mar.'),
  ('suite',        'Suite',         2, 2, 'Suite premium con terraza privada y vista panorámica.')
ON CONFLICT (category_id) DO UPDATE
  SET display_name = EXCLUDED.display_name,
      description  = EXCLUDED.description;

-- =============================================================================
-- 2. TARIFAS BASE (ADR ponderado ≈ USD 130, cerca del USD 120 del PDF)
-- =============================================================================
INSERT INTO rates (category_id, price_usd, effective_from, effective_to)
SELECT category_id, price, '2026-01-01'::date, '2099-12-31'::date
FROM (VALUES
  ('single',        90.00),
  ('double',       120.00),
  ('twin',         120.00),
  ('junior_suite', 180.00),
  ('suite',        280.00)
) AS v(category_id, price)
ON CONFLICT DO NOTHING;

-- =============================================================================
-- 3. HABITACIONES (80 en total)
--    Piso 1: 20 single (101-120)
--    Piso 2: 30 double (201-230)
--    Piso 3: 15 twin   (301-315)
--    Piso 4: 10 junior_suite (401-410)
--    Piso 5: 5  suite  (501-505)
-- =============================================================================
INSERT INTO rooms (room_number, category_id, floor)
SELECT (100 + i)::text, 'single', 1
FROM generate_series(1, 20) AS i
ON CONFLICT (room_number) DO NOTHING;

INSERT INTO rooms (room_number, category_id, floor)
SELECT (200 + i)::text, 'double', 2
FROM generate_series(1, 30) AS i
ON CONFLICT (room_number) DO NOTHING;

INSERT INTO rooms (room_number, category_id, floor)
SELECT (300 + i)::text, 'twin', 3
FROM generate_series(1, 15) AS i
ON CONFLICT (room_number) DO NOTHING;

INSERT INTO rooms (room_number, category_id, floor)
SELECT (400 + i)::text, 'junior_suite', 4
FROM generate_series(1, 10) AS i
ON CONFLICT (room_number) DO NOTHING;

INSERT INTO rooms (room_number, category_id, floor)
SELECT (500 + i)::text, 'suite', 5
FROM generate_series(1, 5) AS i
ON CONFLICT (room_number) DO NOTHING;

-- =============================================================================
-- 4. POLÍTICAS (JSONB key/value que el agente Reservas consulta)
-- =============================================================================
INSERT INTO policies (policy_key, value, description) VALUES
  ('cancellation_brackets',
   '[
      {"min_days_before": 7,  "refund_percent": 100},
      {"min_days_before": 2,  "refund_percent": 50},
      {"min_days_before": 0,  "refund_percent": 0}
   ]'::jsonb,
   'Refund según anticipación al check-in: >=7d=100%, 2-7d=50%, <48h=0%.'),

  ('refund_auto_cap_usd',
   '200'::jsonb,
   'Monto máximo que el agente Reservas puede devolver sin escalar a humano.'),

  ('payment_hold_ttl_hours',
   '24'::jsonb,
   'Horas que la habitación queda bloqueada esperando confirmación manual de pago.'),

  ('payment_reminder_hours',
   '6'::jsonb,
   'Cada cuántas horas el sistema reenvía "ya pagaste?" antes de cancelar.'),

  ('payment_max_reminders',
   '2'::jsonb,
   'Cantidad máxima de recordatorios antes de cancelar la reserva pending_payment.'),

  ('checkin_age_min',
   '18'::jsonb,
   'Edad mínima del huésped principal de la reserva.'),

  ('pets_allowed',
   'false'::jsonb,
   'El hotel no admite mascotas en MVP.'),

  ('smoking_allowed',
   'false'::jsonb,
   'Habitaciones libres de humo. Multa USD 150 si se detecta.'),

  ('walk_in_allowed',
   'true'::jsonb,
   'Se aceptan reservas para el mismo día sujeto a disponibilidad.'),

  ('max_modifications_per_day',
   '3'::jsonb,
   'Tope de modificaciones por reserva por día (anti-sondeo de precios).')
ON CONFLICT (policy_key) DO UPDATE
  SET value = EXCLUDED.value,
      description = EXCLUDED.description;

-- =============================================================================
-- 5. STATIC FACTS (respuestas pre-aprobadas, multilenguaje)
-- =============================================================================
INSERT INTO static_facts (fact_key, values_by_lang, description) VALUES
  ('hotel_name',
   '{"es":"Hotel Bahía Serena","en":"Bahía Serena Hotel"}'::jsonb,
   'Nombre del hotel.'),

  ('hotel_address',
   '{"es":"Av. Roosevelt y Parada 5, Punta del Este, Uruguay","en":"Av. Roosevelt and Parada 5, Punta del Este, Uruguay"}'::jsonb,
   'Dirección física.'),

  ('hotel_phone',
   '{"es":"+598 4244 5500","en":"+598 4244 5500"}'::jsonb,
   'Teléfono recepción.'),

  ('hotel_email',
   '{"es":"hotelia2026@gmail.com","en":"hotelia2026@gmail.com"}'::jsonb,
   'Email del hotel (MVP).'),

  ('wifi_ssid',
   '{"es":"BahiaSerena_Guest","en":"BahiaSerena_Guest"}'::jsonb,
   'SSID de la red WiFi para huéspedes.'),

  ('wifi_password',
   '{"es":"BahiaSerena2026","en":"BahiaSerena2026"}'::jsonb,
   'Password WiFi (placeholder para MVP, rotar en producción).'),

  ('checkin_time',
   '{"es":"El check-in es desde las 15:00 hs.","en":"Check-in is from 3:00 PM."}'::jsonb,
   'Hora de check-in.'),

  ('checkout_time',
   '{"es":"El check-out es hasta las 11:00 hs.","en":"Check-out is until 11:00 AM."}'::jsonb,
   'Hora de check-out.'),

  ('breakfast_hours',
   '{"es":"Desayuno buffet de 7:00 a 10:30 hs en el restaurante del primer piso.","en":"Breakfast buffet from 7:00 AM to 10:30 AM on the first floor restaurant."}'::jsonb,
   'Horario del desayuno.'),

  ('front_desk_hours',
   '{"es":"Recepción 24 horas, todos los días.","en":"24-hour front desk, every day."}'::jsonb,
   'Horario de recepción.'),

  ('pool_hours',
   '{"es":"La piscina está abierta de 8:00 a 21:00 hs.","en":"The pool is open from 8:00 AM to 9:00 PM."}'::jsonb,
   'Horario de la piscina.'),

  ('parking_info',
   '{"es":"Estacionamiento techado sin cargo, sujeto a disponibilidad.","en":"Free covered parking, subject to availability."}'::jsonb,
   'Información de estacionamiento.'),

  ('emergency_contact',
   '{"es":"Para emergencias durante la estadía: marcar 9 desde el teléfono de la habitación o llamar a +598 4244 5500.","en":"For emergencies during your stay: dial 9 from the room phone or call +598 4244 5500."}'::jsonb,
   'Contacto de emergencia.')
ON CONFLICT (fact_key) DO UPDATE
  SET values_by_lang = EXCLUDED.values_by_lang,
      description    = EXCLUDED.description;

-- =============================================================================
-- 6. CATÁLOGO DE UPSELLS (Lifecycle)
-- =============================================================================
INSERT INTO upsell_catalog
  (upsell_id, display_name_es, display_name_en, description, price_usd, available_in_phase)
VALUES
  ('late_checkout',
   'Late checkout (hasta 16:00)',
   'Late checkout (until 4:00 PM)',
   'Extiende tu check-out hasta las 16:00 hs por un cargo adicional.',
   25.00, 'pre_stay'),

  ('early_checkin',
   'Early check-in (desde 10:00)',
   'Early check-in (from 10:00 AM)',
   'Ingresá a tu habitación a partir de las 10:00 hs sujeto a disponibilidad.',
   25.00, 'pre_stay'),

  ('room_upgrade_double_to_suite',
   'Upgrade a Suite',
   'Upgrade to Suite',
   'Mejorá tu habitación Double a Suite. Cargo por noche.',
   80.00, 'pre_stay'),

  ('breakfast_premium',
   'Desayuno premium',
   'Premium breakfast',
   'Desayuno premium con champagne y opciones gourmet.',
   15.00, 'pre_stay'),

  ('welcome_bottle',
   'Botella de bienvenida',
   'Welcome bottle',
   'Botella de espumante regional y plato de quesos a tu llegada.',
   30.00, 'pre_stay'),

  ('spa_massage_60min',
   'Masaje de 60 minutos',
   '60-minute massage',
   'Sesión de masaje relajante en nuestro spa.',
   80.00, 'in_stay')
ON CONFLICT (upsell_id) DO UPDATE
  SET display_name_es = EXCLUDED.display_name_es,
      display_name_en = EXCLUDED.display_name_en,
      description     = EXCLUDED.description,
      price_usd       = EXCLUDED.price_usd;

-- =============================================================================
-- 7. HUÉSPEDES DE PRUEBA
-- =============================================================================
INSERT INTO guests
  (guest_id, full_name, email, phone, language_pref, vip_flag, consent_marketing, consent_updated_at)
VALUES
  -- Huésped 1: María López — uruguaya, español, opt-in marketing
  ('11111111-1111-1111-1111-111111111111',
   'María López',
   'maria.lopez@example.uy',
   '+59899123456',
   'es', FALSE, TRUE, NOW()),

  -- Huésped 2: John Smith — americano, inglés, opt-out marketing
  ('22222222-2222-2222-2222-222222222222',
   'John Smith',
   'john.smith@example.com',
   '+14155551234',
   'en', FALSE, FALSE, NOW())
ON CONFLICT (guest_id) DO NOTHING;

-- =============================================================================
-- 8. RESERVA DE PRUEBA (María, double room 201, 2 noches, confirmada y pagada)
-- =============================================================================
INSERT INTO reservations
  (reservation_id, guest_id, room_id, check_in, check_out,
   status, payment_status, total_amount_usd, source, n_adults, n_children, notes)
SELECT
  '33333333-3333-3333-3333-333333333333',
  '11111111-1111-1111-1111-111111111111',
  r.room_id,
  '2026-06-01'::date,
  '2026-06-03'::date,
  'confirmed', 'paid', 240.00, 'direct', 2, 0,
  'Reserva de prueba — seed inicial.'
FROM rooms r
WHERE r.room_number = '201'
ON CONFLICT (reservation_id) DO NOTHING;

-- =============================================================================
-- 9. CONVERSACIÓN + MENSAJES DE PRUEBA  (web_chat con María)
-- =============================================================================
INSERT INTO conversations
  (conversation_id, guest_id, external_identifier, channel, state, current_phase,
   active_reservation_id)
VALUES
  ('44444444-4444-4444-4444-444444444444',
   '11111111-1111-1111-1111-111111111111',
   '+59899123456',
   'web_chat',
   'active',
   'pre_stay',
   '33333333-3333-3333-3333-333333333333')
ON CONFLICT (conversation_id) DO NOTHING;

INSERT INTO messages
  (conversation_id, trace_id, direction, role, content)
VALUES
  ('44444444-4444-4444-4444-444444444444',
   uuid_generate_v4(), 'inbound',  'guest',
   'Hola! Soy María, tengo una reserva para el 1 de junio. ¿A qué hora puedo hacer check-in?'),

  ('44444444-4444-4444-4444-444444444444',
   uuid_generate_v4(), 'outbound', 'agent',
   'Hola María! Tu check-in es a partir de las 15:00 hs. Si llegás antes podés dejar el equipaje en recepción. 🌊')
ON CONFLICT DO NOTHING;

-- =============================================================================
-- 10. SANITY CHECKS (lanzan error si algo quedó mal)
-- =============================================================================
DO $$
DECLARE
  n_rooms      INT;
  n_categories INT;
  n_rates      INT;
BEGIN
  SELECT COUNT(*) INTO n_rooms      FROM rooms;
  SELECT COUNT(*) INTO n_categories FROM room_categories;
  SELECT COUNT(*) INTO n_rates      FROM rates;

  IF n_rooms <> 80 THEN
    RAISE EXCEPTION 'Esperaba 80 habitaciones, obtuve %', n_rooms;
  END IF;
  IF n_categories <> 5 THEN
    RAISE EXCEPTION 'Esperaba 5 categorías, obtuve %', n_categories;
  END IF;
  IF n_rates < 5 THEN
    RAISE EXCEPTION 'Esperaba >=5 tarifas, obtuve %', n_rates;
  END IF;

  RAISE NOTICE 'Seeds aplicados OK: % habitaciones, % categorías, % tarifas.',
    n_rooms, n_categories, n_rates;
END $$;

COMMIT;
