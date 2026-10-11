# Iteración 2 — Entrada por voz

## Contexto

La Iteración 1 dejó el flujo completo (matcher → service → notifier) funcionando contra
texto tipeado. Esta iteración reemplaza "tipear un nombre" por "decir un nombre con un
hotkey apretado", sin tocar `WeaknessService`, `PokemonRepository` ni `Notifier` -- ese es
exactamente el punto de haberlos puesto detrás de ports desde la Iteración 1.

Pieza nueva: `WhisperTranscriber` (implementa `ports/transcriber.py`, ya definido y sin
adapter), captura de audio con `sounddevice`, hotkey con `keyboard`, y el primer
`controller/` real del proyecto: `VoiceController`.

**El REPL de texto no se reemplaza, se complementa.** Queda como entrada alternativa
mientras la voz es nueva y puede fallar — ambas rutas terminan llamando al mismo
`WeaknessService.get_report()`.

## Hallazgos de esta sesión (verificados, no supuestos)

1. **`faster-whisper` corre sobre CTranslate2, sin backend AMD** (ya establecido en la
   Iteración 1, Apéndice A). Nada nuevo acá, pero el Paso 0 de esta iteración sigue siendo
   medir antes de fijar el tamaño de modelo.
2. **`faster-whisper.transcribe()` tiene `initial_prompt` y `hotwords`** (verificado contra
   el código fuente en la Iteración 1) -- se pueden usar para sesgar el decoder hacia
   nombres de Pokémon, mejorando la transcripción antes incluso de llegar al fuzzy match.
3. **La librería `keyboard` (la que pide el stack original) está "currently unmaintained"
   según su propio README**, con 401 issues abiertos. Verificado ahora, no es un supuesto.
   Sigue funcionando para el caso de uso simple que necesitamos (un hotkey global en
   Windows, sin privilegios de admin), y como no está detrás de ningún port -- el prompt
   original la cablea directo en `main.py`, no como adapter -- cambiarla más adelante por
   `pynput` (activamente mantenida, también soporta mouse) es un cambio contenido a
   `main.py`, no un problema de arquitectura. Se mantiene la decisión original del stack;
   esto es sólo una advertencia archivada para el futuro, no un bloqueante hoy.
4. **`keyboard` corre sus callbacks en un hilo separado del principal**, y soporta
   `on_press_key` / `on_release_key` por separado -- es decir, técnicamente permite
   "push-to-talk" (grabar mientras se mantiene apretada la tecla). Esto habilita la decisión
   de UX de la sección siguiente, pero introduce un problema real de threading (ver
   Decisión 3).

## Decisiones de diseño

### 1. Modo de activación del hotkey -- **pregunta abierta, no decidida acá**

Tres variantes posibles, todas viables con `keyboard`:

- **Push-to-talk**: mantener la tecla apretada mientras se habla, soltarla corta la
  grabación. Más natural para decir un nombre corto en medio de un combate, pero exige
  mantener presionada una tecla con una mano mientras la otra sigue en el control/mouse del
  emulador.
- **Toggle**: un apretón empieza a grabar, otro apretón corta. No hay que sostener nada,
  pero hay que acordarse de cortar (o usar `vad_filter` de Whisper para que corte sola al
  detectar silencio).
- **Ventana fija**: un apretón, se graban N segundos fijos (ej. 2.5s) sin importar cuándo
  se suelte la tecla. Más simple de implementar, pero corta mal si el nombre es largo
  ("Tyranitar") o sobra silencio si es corto ("Mew").

Recomiendo push-to-talk combinado con `vad_filter` como red de seguridad, pero es una
decisión de cómo jugás en la práctica (qué mano tenés libre, si el emulador usa teclado o
gamepad) -- la dejo pendiente de tu confirmación antes de implementar.

### 2. Qué tecla / combinación

Pendiente de tu preferencia -- no hay una "correcta" acá, depende de qué teclas ya usa el
emulador. Candidatas típicas que no suelen chocar: una tecla de función (F9-F12) o una
combinación con modificador (`ctrl+shift+p`).

### 3. El problema de threading que hay que resolver (no es opcional)

`SqlitePokemonRepository` abre su conexión con `sqlite3.connect(...)` en el hilo donde
corre `main.py` (el composition root). El módulo `sqlite3` de Python, **por default,
prohíbe usar esa misma conexión desde un hilo distinto al que la creó** -- tira
`ProgrammingError: SQLite objects created in a thread can only be used in that same thread`.

El hallazgo 4 de arriba confirma que `keyboard` ejecuta sus callbacks en un hilo propio. Si
`VoiceController` llamara a `WeaknessService.get_report()` directo desde ese callback,
rompería la primera vez que alguien use el hotkey.

**Decisión:** en vez de pasar `check_same_thread=False` (que sólo mueve el problema --
seguiría siendo inseguro si dos llamadas coinciden en el tiempo), `VoiceController` NO
llama al service directo desde el callback del hotkey. Encola el resultado de la
transcripción en una `queue.Queue` thread-safe, y un único loop consumidor -- el mismo
loop de `main.py` que hoy atiende el REPL -- la drena y recién ahí llama a
`WeaknessService`/`Notifier`. Así *toda* la lógica de negocio sigue corriendo siempre en un
solo hilo, sin flags inseguros ni locks manuales.

Esto es la misma clase de problema que ya está anotado para la Iteración 3 (el callback de
`keyboard` vs. el event loop de Qt) -- mismo patrón de solución: nunca tocar estado
compartido desde el hilo del hotkey, encolar y procesar en un solo lugar.

### 4. NameMatcher: no se cambia todavía

`RapidFuzzNameMatcher` ya existe, ya está testeado, y el port permite reemplazarlo sin
tocar el service. **No** voy a escribir un matcher fonético en español preventivamente --
se mide qué tan bien tolera los errores reales de Whisper una vez que haya transcripciones
reales, y sólo si hace falta se escribe un segundo adapter. Cambiar algo que funciona por
algo hipotéticamente mejor, sin evidencia, es la clase de over-engineering que este proyecto
viene evitando a propósito.

### 5. Modelo de Whisper: Paso 0, no una decisión de hoy

Igual que quedó dicho en el Apéndice A de la Iteración 1: no se fija `tiny`/`base`/`small`
en este documento. El primer paso de la implementación es un benchmark real contra el
i5-12400F, con los criterios de éxito de la sección de Verificación.

## Plan de ejecución

**Paso 0 -- Benchmark.** Script chico y descartable (no entra al repo final) que carga cada
tamaño de modelo (`tiny`, `base`, `small`) con `compute_type="int8"`, transcribe un clip de
2-3 segundos pregrabado diciendo un nombre de Pokémon, y mide tiempo de carga del modelo +
tiempo de transcripción. Con eso se fija el tamaño antes de seguir.

**Paso 1 -- `WhisperTranscriber`.** Implementa `ports/transcriber.py`. Usa `initial_prompt`
con una muestra de nombres de Pokémon (no los 1025 -- hay un límite de tokens de contexto;
alcanza con los más comunes o ambiguos) y/o `hotwords`. `vad_filter=True` para cortar
silencio. Carga el modelo una sola vez en el constructor, nunca por llamada.

**Paso 2 -- Captura de audio.** `sounddevice.InputStream` o `sounddevice.rec()`, mono,
16kHz (lo que espera Whisper). Buffer en memoria, no archivo temporal.

**Paso 3 -- `VoiceController`.** Registra el hotkey elegido (Decisiones 1-2), arranca/corta
grabación, llama al transcriber, y encola el texto resultante (Decisión 3) -- no llama al
service directo.

**Paso 4 -- `main.py`.** Extiende el loop del REPL para además drenar la cola de
`VoiceController` en cada iteración, y procesar esas entradas exactamente igual que una
línea tipeada.

**Paso 5 -- Tests.** `VoiceController` se testea con un `FakeTranscriber` (nuevo fake en
`tests/fakes.py`) y verificando que lo que llega a la cola es correcto -- sin tocar
`sounddevice` ni `keyboard` reales en la suite automática (no hay micrófono en CI).

## Verificación

| Caso | Criterio |
|---|---|
| Benchmark de modelo | Tiempo fin-de-habla → texto. Umbral de aceptación a definir una vez que haya un número real: referencia informal, <2s se considera cómodo para un combate por turnos. |
| Decir "Charizard" claro | Transcribe y matchea a `charizard` |
| Decir un nombre con acento/mal pronunciado | El `initial_prompt`/`hotwords` + el fuzzy match existente deberían absorberlo -- si no, es señal de que hace falta ajustar el matcher (Decisión 4), no el transcriber |
| Grabar silencio (nadie habla) | `vad_filter` corta, no llega una query vacía al matcher (ya hay una guarda para esto en `RapidFuzzNameMatcher.match`) |
| Usar el hotkey y el REPL de texto alternadamente en la misma sesión | Ambos funcionan sin errores de threading de SQLite |

## Qué queda explícitamente afuera

Overlay visual y TTS (Iteración 3). Mejorar el matcher más allá de rapidfuzz, salvo que el
benchmark real contra Whisper muestre que hace falta.
