# Contexto del proyecto: Asistente de debilidades Pokémon

## Objetivo
Quiero construir un asistente que, mientras juego un juego Pokémon en emulador de PC,
me diga las debilidades de tipo del Pokémon rival en pantalla. La entrada puede ser por
comando de voz (decir el nombre del rival) y, a futuro, por reconocimiento automático en
pantalla (OCR o sprite matching). La salida es un overlay visual transparente sobre el
juego, con opción de texto a voz (TTS).

## Alcance del MVP actual
1. Comando de voz con hotkey → transcripción → fuzzy match contra nombres de Pokémon →
   búsqueda de debilidades → mostrar resultado en overlay (y opcionalmente hablarlo).
2. Reconocimiento por pantalla (OCR/sprite) queda para una segunda etapa, pero la
   arquitectura debe soportarlo sin refactors grandes.

## Decisiones de arquitectura ya tomadas
- **Lenguaje**: Python de punta a punta. Descartamos C/C++ porque el cuello de botella
  real está en las librerías de inferencia (Whisper, OCR), que ya están optimizadas en
  C/C++ por debajo. El overhead de Python en el resto de la app es irrelevante.
- **Base de datos**: SQLite local. El dataset es chico (~1000-1500 Pokémon), de solo
  lectura en runtime, y con relaciones simples (Pokémon → tipo(s) → debilidades). No se
  justifica NoSQL.
- **La app en runtime NUNCA llama a PokeAPI.** PokeAPI se consume una única vez desde un
  script de ETL (`scripts/build_db.py`) que arma la base local con las debilidades ya
  **precalculadas** (cruzando tipos del Pokémon contra la tabla de efectividades). Esto
  evita depender de internet o de la estructura del JSON de un tercero durante el juego.
- **Arquitectura**: hexagonal (ports & adapters), con estas capas:
  - `domain/`: entidades puras (`Pokemon`, `Weakness`), sin dependencias externas.
  - `ports/`: interfaces (`Protocol`) que expresan necesidades en términos del dominio,
    no de las librerías concretas. Ej: `Transcriber`, `ScreenReader`, `Notifier`,
    `PokemonRepository`.
  - `adapters/`: implementaciones concretas de cada port usando una librería puntual
    (ej: `WhisperTranscriber` implementa `Transcriber`; `SqlitePokemonRepository`
    implementa `PokemonRepository`). Permite reemplazar cualquier integración externa
    sin tocar lógica de negocio.
  - `service/`: lógica de negocio y orquestación (`WeaknessService`), depende solo de
    ports.
  - `controller/`: puntos de entrada por evento (`VoiceController`, futuro
    `VisionController`), orquestan entrada → service → notifier, sin lógica de negocio
    propia.
  - `main.py`: composition root, único lugar donde se instancian los adapters concretos
    y se inyectan en services/controllers.
- Se decidió priorizar velocidad de desarrollo e iteración por sobre micro-optimización,
  dado que el techo de performance del proyecto está en la calidad del reconocimiento
  de voz/OCR, no en el lenguaje o la arquitectura del resto de la app.

## Estructura de carpetas acordada
```
pokemon-assistant/
├── domain/
│   ├── pokemon.py              # dataclasses Pokemon, Weakness
│   └── exceptions.py           # PokemonNotFoundError, etc.
├── ports/
│   ├── pokemon_repository.py
│   ├── transcriber.py
│   ├── screen_reader.py
│   └── notifier.py
├── adapters/
│   ├── repository/
│   │   └── sqlite_pokemon_repository.py
│   ├── transcriber/
│   │   └── whisper_transcriber.py
│   ├── screen_reader/
│   │   ├── tesseract_screen_reader.py
│   │   └── easyocr_screen_reader.py
│   └── notifier/
│       ├── overlay_notifier.py
│       ├── tts_notifier.py
│       └── composite_notifier.py
├── service/
│   └── weakness_service.py
├── controller/
│   ├── voice_controller.py
│   └── vision_controller.py    # segunda etapa
├── scripts/
│   └── build_db.py             # ETL desde PokeAPI, corre aparte del runtime
├── data/
│   └── pokedex.db
└── main.py
```

## Stack técnico
- **Voz**: `faster-whisper` (modelo `small` para arrancar), `sounddevice` para captura
  de audio, `keyboard` para hotkey, `rapidfuzz` para matching difuso de nombres.
- **Pantalla / OCR** (segunda etapa): `mss` para captura de región de pantalla,
  `pytesseract` o `easyocr`, `Pillow` para preprocesamiento (upscale, binarización),
  `imagehash` como respaldo por sprite matching.
- **Datos**: `sqlite3` (stdlib), `requests` para el ETL contra PokeAPI.
- **Overlay / salida**: `PyQt6` para ventana transparente sin bordes sobre el juego,
  `pyttsx3` para TTS local (o `edge-tts` si se prioriza calidad de voz sobre
  funcionamiento offline).

## Esquema SQLite acordado
```sql
CREATE TABLE pokemon (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type1 TEXT NOT NULL,
    type2 TEXT,
    ability TEXT
);

CREATE TABLE weaknesses (
    pokemon_id INTEGER,
    weak_type TEXT NOT NULL,
    multiplier REAL NOT NULL,
    FOREIGN KEY (pokemon_id) REFERENCES pokemon(id)
);
```
Runtime query esperada (sin cómputo, sin red):
```sql
SELECT weak_type, multiplier FROM weaknesses
WHERE pokemon_id = ? AND multiplier > 1
ORDER BY multiplier DESC;
```

## Lo que se necesita ahora
Quiero que armes el proyecto Python siguiendo exactamente esta arquitectura y stack.
Empezá por:
1. `scripts/build_db.py`: ETL que consulta PokeAPI (endpoints de pokémon y de tipos con
   `damage_relations`), calcula las debilidades por Pokémon, y puebla `data/pokedex.db`
   con el esquema de arriba.
2. El `domain/`, los `ports/` (como `Protocol`), y el `SqlitePokemonRepository`.
3. El `WeaknessService`.
4. El flujo de voz completo: `WhisperTranscriber`, `VoiceController`, un
   `OverlayNotifier` básico con PyQt6 y un `TtsNotifier` con `pyttsx3`, combinados con
   `CompositeNotifier`.
5. `main.py` como composition root, cableando todo y registrando el hotkey.

Priorizá que el código sea testeable (los controllers y services deben poder probarse
con fakes de los ports, sin llamar a librerías reales) y que cada adapter esté
desacoplado del resto del sistema. El reconocimiento por pantalla (OCR/sprite) queda
para una iteración posterior — dejá el `port` de `ScreenReader` definido pero no
implementes los adapters todavía, salvo que lo pida explícitamente.
