"""Port: salida hacia el usuario. Iteración 1 tiene un solo adapter
(`ConsoleNotifier`); `OverlayNotifier`, `TtsNotifier` y `CompositeNotifier`
llegan en la iteración 3 sin tocar el service ni el controller."""
from __future__ import annotations

from typing import Protocol

from domain.pokemon import AbilityCaveat, WeaknessReport


class Notifier(Protocol):
    def notify_weakness_report(self, report: WeaknessReport) -> None: ...

    def notify_ability_info(self, ability: AbilityCaveat) -> None: ...
