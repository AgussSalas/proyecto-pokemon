"""Tabla curada a mano: qué habilidades afectan qué tipos y cómo.

PokeAPI no expone esto en forma estructurada (el efecto de cada habilidad en
/ability/{id} es sólo texto libre en inglés/alemán/francés), así que se
mantiene como literal versionado. Ver Apéndice B del plan.

Nunca se usa para ajustar el multiplicador que calcula el ETL: sólo se anota
como advertencia en el reporte (ver decisión de randomlockes, sección 2 del
plan). is_approx=True marca habilidades cuyo efecto real depende del
movimiento concreto (p. ej. Antibalas bloquea ciertos movimientos, no un
tipo entero) y por lo tanto no es 100% fiel modelarlas como "afecta a un
tipo".
"""
from __future__ import annotations

# ability (slug PokeAPI), affected_type (None = todos), kind, factor, note_es, is_approx
# kind: 'immune' (factor None) | 'multiply' (factor requerido) | 'special' (factor None)
ABILITY_TYPE_EFFECTS: list[tuple[str, str | None, str, float | None, str, bool]] = [
    ("levitate", "ground", "immune", None,
     "Levitación: inmune a Tierra", False),
    ("flash-fire", "fire", "immune", None,
     "Mar Llamas: inmune a Fuego (y sube su propio Fuego)", False),
    ("water-absorb", "water", "immune", None,
     "Absorbe Agua: inmune a Agua (recupera PS)", False),
    ("volt-absorb", "electric", "immune", None,
     "Absorbe Electricidad: inmune a Eléctrico (recupera PS)", False),
    ("lightning-rod", "electric", "immune", None,
     "Pararrayos: inmune a Eléctrico (y sube Ataque Especial)", False),
    ("motor-drive", "electric", "immune", None,
     "Motor Eléctrico: inmune a Eléctrico (y sube Velocidad)", False),
    ("storm-drain", "water", "immune", None,
     "Absorbe Agua (Storm Drain): inmune a Agua (y sube Ataque Especial)", False),
    ("sap-sipper", "grass", "immune", None,
     "Estimulante: inmune a Planta (y sube Ataque)", False),
    ("dry-skin", "water", "immune", None,
     "Piel Seca: inmune a Agua (recupera PS)", False),
    ("dry-skin", "fire", "multiply", 1.25,
     "Piel Seca: recibe 25% más daño de Fuego", False),
    ("earth-eater", "ground", "immune", None,
     "Devora Tierra: inmune a Tierra (recupera PS)", False),
    ("well-baked-body", "fire", "immune", None,
     "Cuerpo Bizcocho: inmune a Fuego (sube Defensa)", False),
    ("thick-fat", "fire", "multiply", 0.5,
     "Sebo: recibe la mitad de Fuego", False),
    ("thick-fat", "ice", "multiply", 0.5,
     "Sebo: recibe la mitad de Hielo", False),
    ("heatproof", "fire", "multiply", 0.5,
     "Ignífugo: recibe la mitad de Fuego", False),
    ("water-bubble", "fire", "multiply", 0.5,
     "Burbuja de Agua: recibe la mitad de Fuego", False),
    ("purifying-salt", "ghost", "multiply", 0.5,
     "Sal Purificadora: recibe la mitad de Fantasma", False),
    ("filter", None, "multiply", 0.75,
     "Filtro: -25% en golpes súper efectivos (todos los tipos)", False),
    ("solid-rock", None, "multiply", 0.75,
     "Roca Sólida: -25% en golpes súper efectivos (todos los tipos)", False),
    ("prism-armor", None, "multiply", 0.75,
     "Armadura Prisma: -25% en golpes súper efectivos (todos los tipos)", False),
    ("fluffy", "fire", "multiply", 2.0,
     "Peluche: recibe EL DOBLE de Fuego (aparte, la mitad en movimientos de contacto)", True),
    ("wonder-guard", None, "special", None,
     "Superguarda: sólo le afectan movimientos súper efectivos", False),
    ("bulletproof", None, "special", None,
     "Antibalas: bloquea movimientos de bomba/proyectil concretos, no un tipo entero", True),
    ("soundproof", None, "special", None,
     "Insonorizar: bloquea movimientos de sonido concretos, no un tipo entero", True),
    ("wind-rider", None, "special", None,
     "Viento Afín: bloquea movimientos de viento concretos, no un tipo entero", True),
]
