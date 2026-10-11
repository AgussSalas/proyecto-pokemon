"""Adapter: salida por consola. Formato acordado en la sección 2 del plan."""
from __future__ import annotations

from domain.pokemon import AbilityCaveat, WeaknessReport


class ConsoleNotifier:
    def notify_weakness_report(self, report: WeaknessReport) -> None:
        pokemon = report.pokemon
        type_label = "/".join(pokemon.type_names_es)
        print(f"{pokemon.name.capitalize()} ({type_label}) — Gen {pokemon.generation}")

        if not report.weaknesses:
            print("  Sin debilidades en esta generación.")
        else:
            by_multiplier: dict[float, list[str]] = {}
            for w in report.weaknesses:
                by_multiplier.setdefault(w.multiplier, []).append(w.type_name_es)
            for multiplier in sorted(by_multiplier, reverse=True):
                mult_label = f"×{multiplier:g}"
                print(f"  {mult_label}  {', '.join(by_multiplier[multiplier])}")

        for caveat in report.ability_caveats:
            self._print_caveat(caveat)

    def notify_ability_info(self, ability: AbilityCaveat) -> None:
        self._print_caveat(ability, prefix="")

    def _print_caveat(self, caveat: AbilityCaveat, prefix: str = "⚠ Si tiene ") -> None:
        hidden_tag = " (oculta)" if caveat.is_hidden else ""
        if caveat.effect_note_es:
            approx_tag = " [aprox.]" if caveat.is_approx else ""
            print(f"  {prefix}{caveat.display_name}{hidden_tag}: {caveat.effect_note_es}{approx_tag}")
        else:
            print(f"  {prefix}{caveat.display_name}{hidden_tag}: sin efecto conocido sobre tipos")
