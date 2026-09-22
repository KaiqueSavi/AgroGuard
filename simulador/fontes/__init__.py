"""
AgroGuard IA — Fontes de dados simuladas (telemetria, ambiente, operação)
==========================================================================

Cada módulo deste pacote expõe `amostrar(linha, agora, rng) -> dict`,
produzindo EXATAMENTE o bloco do payload aninhado de `POST /telemetria`
que lhe pertence (mesma forma de `agroguard.api.schemas`), com um jitter
gaussiano pequeno sobre uma linha real do dataset sintético — para que
execuções repetidas pareçam dado ao vivo, mas continuem dentro das
faixas do schema e consistentes com as regras de negócio de
`agroguard.telemetria.servico`.
"""
