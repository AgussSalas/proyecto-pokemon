class PokemonNotFoundError(Exception):
    """No se encontró ningún Pokémon que matchee `query`, o la especie no
    existía todavía en la generación consultada."""

    def __init__(self, query: str) -> None:
        self.query = query
        super().__init__(f"No se encontró un Pokémon para: {query!r}")
