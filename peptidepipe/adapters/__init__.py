"""Adapters package. Importing it registers every concrete scorer into the
core registry, so `registry.build(name)` works for any name a config selects.
Core code never imports a specific adapter — it imports this package (or relies
on the CLI doing so), keeping engine choice in CONFIG."""
from peptidepipe.adapters import affinity_autodock  # noqa: F401  (registers "autodock4zn")
from peptidepipe.adapters import affinity_boltz2     # noqa: F401  (registers "boltz2")
