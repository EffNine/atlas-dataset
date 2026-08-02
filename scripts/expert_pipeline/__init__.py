"""Atlas Expert Pipeline — 6500 pilot extraction runner.

Modular pipeline: source adapters -> expert record converter -> validation
(schema / provenance / license / duplicate / quality gate) -> manifest +
records + quality report. Pilot extraction only; no training, no release.
"""

__version__ = "0.1.0"
