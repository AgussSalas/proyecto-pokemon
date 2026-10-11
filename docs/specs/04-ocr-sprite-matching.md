# Iteración 4 — Reconocimiento automático en pantalla (OCR / sprite matching)

## Contexto

El prompt original marca esta pieza explícitamente como la más especulativa del proyecto:
*"Reconocimiento por pantalla (OCR/sprite) queda para una segunda etapa [...] dejá el port
de `ScreenReader` definido pero no implementes los adapters todavía, salvo que lo pida
explícitamente."* Ese port (`ports/screen_reader.py`) ya existe desde la Iteración 1, sin
adapter, exactamente como se pidió.

Este documento es deliberadamente **más corto y menos prescriptivo** que los anteriores --
no porque el tema sea menos importante, sino porque escribir un plan detallado hoy sobre
algo que depende tan directamente de datos que todavía no tenemos (qué emulador, qué juego,
qué resolución, qué fuente de texto) sería inventar certeza donde no la hay. El objetivo de
este spec es dejar acotado el problema y las preguntas que hace falta responder *cuando*
se llegue a esta iteración, no resolverlas ahora.

## Lo que ya está decidido (del prompt original)

Stack elegido: `mss` (captura de una región de pantalla), `pytesseract` o `easyocr` (OCR),
`Pillow` (preprocesamiento -- upscale, binarización), `imagehash` como respaldo por
comparación de sprites en vez de texto.

## Por qué esto es más difícil de lo que parece a primera vista

Dos enfoques posibles, con un tradeoff de fondo distinto al resto del proyecto:

1. **OCR del nombre en texto** (si el juego muestra el nombre del rival como texto en
   pantalla, típico en el cuadro de diálogo de combate): más simple en principio, pero la
   calidad depende enteramente de la fuente del juego (muchos juegos de Game Boy/GBA usan
   tipografías pixeladas pequeñas, hostiles para OCR sin preprocesamiento agresivo) y de la
   resolución de captura.
2. **Comparación de sprites** (`imagehash` contra una base de sprites conocidos): evita el
   problema de la fuente, pero necesita una base de sprites de referencia por generación/
   juego (no viene gratis de PokeAPI de la misma forma que los datos de tipos) y es más
   sensible a la región exacta de captura y a paletas de color distintas entre juegos.

No hay una respuesta correcta sin saber contra qué juego/emulador se va a usar esto en la
práctica -- a diferencia de la Iteración 1 (donde PokeAPI es la misma fuente sin importar
qué juegues), acá el "dato de entrada" es la UI específica de un juego específico.

## Preguntas a responder cuando se llegue a esta iteración (no ahora)

1. ¿Qué emulador y qué juego concretos -- el mismo que se use para las Iteraciones 2-3, u
   otro?
2. ¿El nombre del rival aparece como texto en pantalla en algún momento del combate (la
   mayoría de los juegos Pokémon sí lo hacen), o habría que identificarlo sólo por sprite?
3. ¿A qu��� resolución corre el emulador? Define si hace falta el upscale de `Pillow` antes
   de pasarle la imagen a `pytesseract`, y cuánto.
4. Si se necesita una base de sprites para `imagehash`: ¿se puede extraer de PokeAPI (los
   sprites oficiales existen ahí, `/pokemon/{id}.sprites`), o hace falta capturarlos del
   juego específico porque los sprites in-game no coinciden pixel a pixel con los de
   PokeAPI?

## Lo único que se puede decidir de antemano

- El port `ScreenReader` ya tiene la firma correcta (`read_region(region) -> str`) y no
  necesita cambiar según la respuesta a las preguntas de arriba -- eso ya está validado
  desde la Iteración 1.
- Cualquiera sea el enfoque (OCR o sprite), el resultado final sigue siendo un string que
  entra al mismo `NameMatcher` que ya existe -- no hace falta un pipeline de matching nuevo,
  sólo una fuente de texto nueva, igual que la voz fue "una fuente de texto nueva" en la
  Iteración 2.
- Un `VisionController` (mencionado en la estructura de carpetas original) jugaría el mismo
  rol que `VoiceController`: capturar en loop (con throttle -- no tiene sentido leer la
  pantalla más rápido que unas pocas veces por segundo), y encolar el resultado al mismo
  consumidor único que ya centraliza el acceso a la DB (mismo patrón de threading que
  Iteraciones 2 y 3).

## Qué NO se decide en este documento

Framework de preprocesamiento exacto, umbral de confianza del OCR, estructura de la base de
sprites, si se usa `pytesseract` o `easyocr` (el prompt deja ambos como opción). Todo eso
depende de las respuestas a las preguntas de la sección anterior y se decide -- con
investigación real contra el juego/emulador elegido, no por suposición -- cuando se
confirme que esta iteración arranca.
