"""
hotelai.knowledge
==================

Corpus rico del Hotel Bahia Serena usado por el Concierge cuando elige la tool
answer_freeform_question. Le permite responder preguntas generales sobre el
hotel sin inventar datos.

REGLA: Si el huesped pregunta sobre PRECIOS ESPECIFICOS de UNA fecha o
DISPONIBILIDAD ACTUAL, Claude debe delegar a Reservas en vez de responder
desde aca. Aca solo hay precios STANDARDS (rate card) que pueden cambiar por
temporada/promo.
"""

HOTEL_KNOWLEDGE = """\
HOTEL BAHIA SERENA - INFORMACION COMPLETA
==========================================

UBICACION:
- Av. Roosevelt y Parada 5, Punta del Este, Uruguay
- A 200m de la playa Mansa (caminando 3 minutos)
- 800m de Punta Ballena
- 5km del centro de Punta del Este (Av. Gorlero, casino Conrad, puerto, Los Dedos)
- 7km de La Barra
- 15km del aeropuerto Laguna del Sauce (servicio de transfer disponible con cargo)

HABITACIONES (80 en total, en 5 categorias)

1. SINGLE (20 habitaciones, piso 1, USD 90/noche)
   - Una cama individual de 1 plaza (90x190 cm)
   - 18 m2, vista interior al jardin
   - TV LCD 32", aire acondicionado split, caja de seguridad chica
   - Bano privado con ducha, articulos de tocador (shampoo, acondicionador, gel)
   - Escritorio compacto + silla
   - WiFi gratis, secador de pelo, plancha a pedido
   - Ideal para: viajero solo, business trip, estadias cortas

2. DOUBLE (30 habitaciones, piso 2, USD 120/noche)
   - Una cama matrimonial Queen (160x200 cm)
   - Opcionalmente se agrega una cama nido para un tercero (cargo USD 30/noche)
   - 28 m2, vista parcial al mar
   - TV LCD 42", aire split, mini-fridge, caja de seguridad
   - Bano privado con banera o ducha (a eleccion al momento del check-in)
   - Escritorio amplio + sillon individual
   - Ideal para: parejas, viaje romantico
   - DIFERENCIA CLAVE con TWIN: la Double tiene UNA cama grande (mejor para parejas).
     La Twin tiene DOS camas separadas (mejor para amigos o colegas).

3. TWIN (15 habitaciones, piso 3, USD 120/noche)
   - Dos camas individuales separadas (90x200 cm cada una)
   - 28 m2, vista parcial al mar (mismas vistas que la Double pero un piso mas arriba)
   - TV LCD 42", aire split, mini-fridge, caja de seguridad
   - Bano privado con ducha (sin banera en este tipo)
   - Escritorio + sillon
   - Ideal para: amigos, hermanos, colegas viajando juntos, familias con un nino
   - DIFERENCIA CLAVE con DOUBLE: dos camas separadas en vez de una matrimonial.

4. JUNIOR SUITE (10 habitaciones, piso 4, USD 180/noche)
   - Cama King size (180x200 cm)
   - 42 m2 con sala de estar SEPARADA con sofa y TV adicional
   - Vista FRONTAL al mar
   - TV LCD 55", aire split, frigobar premium (bebidas incluidas), cafetera Nespresso con capsulas
   - Bano amplio con banera + ducha de lluvia separadas, amenities premium L'Occitane
   - Bata, pantuflas, kit de bienvenida
   - Ideal para: estadias de 4+ noches, parejas que quieren mas espacio, parejas con un bebe

5. SUITE (5 habitaciones, piso 5 - ultimo piso, USD 280/noche)
   - Cama King size (180x200 cm) con dosel
   - 65 m2 con sala de estar amplia y comedor para 4 personas
   - Vista PANORAMICA al mar + TERRAZA PRIVADA con jacuzzi al aire libre
   - TV LCD 65" + TV adicional en el dormitorio
   - Aire central, frigobar premium (todo incluido), cafetera Nespresso, sistema de
     sonido Bluetooth, Smart TV con Netflix
   - Bano de lujo con banera de hidromasaje y ducha tipo lluvia
   - Bata, pantuflas, amenities Bvlgari, kit completo de bienvenida con espumante
   - Servicio de mayordomo a pedido
   - Ideal para: luna de miel, aniversarios, ocasiones especiales

DESAYUNO BUFFET (incluido en TODAS las tarifas)
- Horario: 7:00 a 10:30 hs
- Lugar: Restaurante "Mar del Sur" en el primer piso, con ventanal al mar
- Modalidad: buffet libre con estaciones tematicas

Que incluye:
- PANADERIA artesanal del dia: medialunas saladas y dulces, croissants, pan de campo,
  pan integral, baguette, pan sin gluten, tostadas
- FRUTAS frescas de estacion (mango, ananas, sandia, melon, frutillas, banana),
  ensaladas de frutas, compotas de manzana y pera
- LACTEOS: yogur natural, yogur griego, yogur con frutas, leche entera y descremada,
  manteca, dulce de leche casero
- CEREALES: corn flakes, all bran, choco krispis, avena, granolas caseras, frutos secos
- ESTACION DE HUEVOS preparados al momento por chef: revueltos, fritos, omelet con
  relleno (hongos, jamon, queso, vegetales)
- CHARCUTERIA: bacon crocante, salchichas de campo, chorizos pequenos, jamon crudo,
  jamon cocido, salame, mortadela
- QUESOS: gouda, brie, port salut, mozzarella, queso de campo, queso azul
- JUGOS FRESCOS exprimidos en el momento: naranja, manzana, pera, smoothie verde
- ESTACION DE CAFE con barista: espresso, americano, cappuccino, latte, flat white,
  macchiato
- TES en hebras (Earl Grey, English Breakfast, verde, manzanilla, menta, frutos rojos,
  rooibos, mate cocido), chocolate caliente
- DULCES: mermeladas caseras (frutilla, durazno, naranja, ciruela), miel de abeja
  local de Maldonado
- Opciones SIN GLUTEN, SIN LACTOSA y VEGANAS disponibles a pedido en la mesa

AMENITIES DEL HOTEL:
- PISCINA exterior CLIMATIZADA, abierta 8:00-21:00, con bar al lado (Pool Bar)
- SOLARIUM con reposeras y servicio de toallas (gratis)
- GIMNASIO 6:00-23:00: equipos de cardio, pesas, mancuernas
- CLASES de yoga matutinas (todos los dias 8:00, 45 min, gratis)
- SPA: sauna seco, sauna humedo, jacuzzi, masajes (a coordinar, con cargo)
- RESTAURANTE "Mar del Sur": desayuno + cena (19:30-23:00), cocina mediterranea con
  toques uruguayos, especialidades en pescados y mariscos
- BAR "ATARDECER" 15:00-1:00 con terraza al mar, cocteleria de autor, picadas
- BUSINESS CENTER 24hs: 4 PCs, impresora, escaner
- SALA DE JUEGOS: pool, ping-pong, futbol de mesa, dardos
- BIBLIOTECA con libros en espanol, ingles y portugues, sillones comodos
- AREA INFANTIL supervisada (10:00-19:00 los fines de semana, gratis)
- BICICLETAS de cortesia (15 unidades, gratis, con casco)
- ESTACIONAMIENTO TECHADO sin cargo (40 lugares, sujeto a disponibilidad)
- LAVANDERIA con servicio express (con cargo)
- ROOM SERVICE 7:00-23:00
- RECEPCION 24 horas con concierge para reservas en restaurantes y excursiones
- Caja de seguridad central
- Wifi gratis en todo el hotel
- Servicio de despertador

ATRACCIONES Y EXCURSIONES CERCANAS:
- PLAYA MANSA (200m): aguas calmas, ideal para familias y nado tranquilo, restaurantes
  parrilla en la orilla
- PLAYA BRAVA (1.5km): playa con olas, ideal surf, area de "Los Dedos" (la mano)
- PUNTA BALLENA (800m): mirador con vista al atardecer espectacular, restaurantes de
  autor, galerias de arte
- CASAPUEBLO de Carlos Paez Vilaro (10 min en auto, transfer disponible USD 20 round
  trip): construccion blanca esculpida en el acantilado, museo, atardecer imperdible
- CENTRO DE PUNTA DEL ESTE (5km): Av. Gorlero (shopping), casino Conrad, puerto deportivo,
  yacht club, mercado del puerto
- LA BARRA (7km): vida nocturna, restaurantes trendy, puente ondulante, playa
- JOSE IGNACIO (45km): pueblo bohemio, playas virgenes, restaurantes top
  (La Huella, Marismo)
- ISLA GORRITI: excursion en lancha desde el puerto (15 min, gratis con dia de playa)
- ISLA DE LOBOS: tour para ver lobos marinos en su habitat (2 horas, con cargo)
- TOURS EN CUATRICICLO por las dunas (con cargo, se contrata en recepcion)
- CATAMARAN AL ATARDECER (con cargo, sale del puerto)
- BODEGAS de Maldonado: ruta del vino, degustaciones (con cargo)

POLITICAS DEL HOTEL:
- CHECK-IN: desde las 15:00 hs (early check-in USD 25 con cargo, sujeto a disponibilidad)
- CHECK-OUT: hasta las 11:00 hs (late check-out USD 25 con cargo)
- MASCOTAS: aceptamos pequenas hasta 10 kg, cargo USD 15/noche, area exterior dedicada,
  no permitidas en restaurant/piscina/gimnasio
- FUMAR: prohibido en habitaciones (multa USD 200 por limpieza profunda), areas
  exteriores designadas en jardin y terraza
- EDAD MINIMA para reservar a su nombre: 18 anos
- MENORES: hasta 6 anos sin cargo en cama matrimonial con padres
- CANCELACION:
  - Mas de 7 dias antes: 100% reintegro
  - Entre 2 y 7 dias antes: 50% reintegro
  - Menos de 48 hs antes: sin reintegro
- CAMBIOS DE FECHA: gratis hasta 48hs antes (sujeto a disponibilidad)
- PAGOS: transferencia bancaria, tarjeta de credito (Visa/Master/Amex), efectivo (USD/UYU)

CONTACTO:
- Telefono recepcion 24 hs: +598 4244 5500
- WhatsApp: +598 4244 5500
- Email: hotelia2026@gmail.com
- Direccion: Av. Roosevelt y Parada 5, Punta del Este, Maldonado, Uruguay

INFO ADICIONAL UTIL:
- Idiomas del staff: espanol, ingles, portugues, basico de aleman e italiano
- Aceptamos pago en USD y UYU al tipo de cambio del dia
- Servicio de transfer desde/hacia el aeropuerto: USD 35 ida (sedan), USD 60 (van)
- Servicio de despertador a la hora indicada en recepcion
- Conexion con servicios medicos privados (Asistencial Maldonado) - llamar 9 desde
  la habitacion
- Toda habitacion incluye: secador de pelo, espejo de aumento, percheros con
  perchas anti-robo, planchador a pedido
"""


# Instrucciones especificas para Claude al usar este corpus
FREEFORM_SYSTEM_PROMPT = f"""\
Sos el Concierge del Hotel Bahia Serena. Tu tarea es responder la pregunta del
huesped usando UNICAMENTE la informacion del corpus que sigue. No inventes datos.

REGLAS:
1. Si la pregunta es sobre algo NO incluido en el corpus, decilo honestamente
   ("dejame chequear con el equipo y te confirmo") en vez de inventar.
2. Si la pregunta es sobre PRECIOS de UNA FECHA ESPECIFICA o DISPONIBILIDAD ACTUAL
   real (ej. "tenes disponible la suite el 15 de junio?"), no respondas desde
   aca - decile al huesped que vas a chequear y un agente le confirma.
3. Tono casual, tuteo uruguayo. Maximo 4-5 oraciones (no abrumar con info).
4. Si el huesped pidio comparar dos habitaciones, da una respuesta clara y
   diferenciadora.
5. Si pregunta "como sabes esto" o "quien sos", contesta cordialmente que sos el
   asistente virtual del hotel.
6. NO mencionar "el corpus", "la base de conocimiento", "soy un LLM", etc.

CORPUS DEL HOTEL:
{HOTEL_KNOWLEDGE}
"""


__all__ = ["HOTEL_KNOWLEDGE", "FREEFORM_SYSTEM_PROMPT"]
