"""DeepDict: an English-Chinese reading-aid dictionary generated with LLMs.

Layout:
  wordlists/  candidate word list builders (frequency lists, corpora, cogsci)
  cli/        pipeline entry points: generate, clean, QA scan, verify, build
  qa/         zero-token risk signals (lookalike detection, ECDICT cross-check)
  build/      Apple Dictionary source rendering
  prompts/    system prompts for generation and verification
"""

__version__ = "2.0.0"
