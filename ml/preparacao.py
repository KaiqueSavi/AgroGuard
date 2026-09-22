"""
AgroGuard IA — Pipeline de preparação de dados (Sprint 3-4 / v0.3)
====================================================================

Trata inconsistências antes do treino e da inferência: duplicidades (exatas e
por chave de negócio), dados faltantes (imputação) e valores fora da faixa
esperada pelo schema (clipagem ou rejeição em modo estrito).

Usado por `ml/train.py` (antes do split) e disponível para qualquer consumidor
que precise higienizar um lote de leituras antes de chamar `ml/inferencia.py`.
"""
from __future__ import annotations

import pandas as pd

# Faixas válidas (inclusivas) por coluna numérica, conforme o schema do banco
# (sql/schema.sql) e o gerador sintético (data/generate_dataset.py).
RANGES: dict[str, tuple[float, float]] = {
    "velocidade_kmh": (0, 120),
    "inclinacao_graus": (0, 45),
    "vibracao_g": (0, 5),
    "precip_24h_mm": (0, 300),
    "precip_prev_6h_mm": (0, 100),
    "umidade_solo": (0, 1),
    "vento_max_kmh": (0, 150),
    "dist_corpo_dagua_m": (0, 10000),
    "declividade_pct": (0, 45),
    "jornada_acumulada_h": (0, 24),
    "dias_desde_manutencao": (0, 365),
    "experiencia_operador_anos": (0, 50),
    "idade_equipamento_anos": (0, 60),
}

# Categorias válidas por coluna categórica (mesmos domínios do gerador
# sintético e das CHECK constraints do banco).
CATEGORIAS_VALIDAS: dict[str, set[str]] = {
    "tipo_equip": {"Colheitadeira", "Trator", "Pulverizador", "Caminhão"},
    "tipo_operacao": {"campo", "transporte", "parado"},
    "turno": {"manha", "tarde", "noite"},
}

# Colunas que formam a chave de negócio de uma leitura de telemetria.
COLUNAS_CHAVE = ["equip_id", "data_hora"]


class DadosInvalidos(ValueError):
    """Levantada quando a preparação não produz nenhuma linha válida, ou —
    em modo `estrito` — quando há valores fora da faixa esperada pelo schema."""


def preparar(df: pd.DataFrame, *, estrito: bool = False) -> tuple[pd.DataFrame, dict]:
    """
    Higieniza `df`: remove duplicidades, preenche faltantes e trata valores
    fora de faixa. Não altera `df` (trabalha sobre uma cópia).

    Parâmetros
    ----------
    estrito : quando True, valores fora de faixa levantam `DadosInvalidos` em
        vez de serem clipados (usado em validações rígidas / testes).

    Retorna
    -------
    (df_limpo, relatorio) — `relatorio` documenta cada transformação aplicada:
        {linhas_entrada, linhas_saida, duplicatas_exatas, duplicatas_chave,
         faltantes_preenchidos: {col: n}, valores_clipados: {col: n},
         rejeitadas: n, motivos: {motivo: n}}

    Levanta `DadosInvalidos` se o resultado ficar vazio.
    """
    linhas_entrada = len(df)
    trabalho = df.copy()
    motivos: dict[str, int] = {}
    rejeitadas_total = 0

    def _rejeitar(mask: pd.Series, motivo: str) -> None:
        nonlocal trabalho, rejeitadas_total
        if mask is None or not mask.any():
            return
        n = int(mask.sum())
        motivos[motivo] = motivos.get(motivo, 0) + n
        rejeitadas_total += n
        trabalho = trabalho.loc[~mask].copy()

    # 1) Linhas sem a chave de negócio (equip_id / data_hora) são rejeitadas ---
    chave_presentes = [c for c in COLUNAS_CHAVE if c in trabalho.columns]
    if chave_presentes:
        mask_sem_chave = trabalho[chave_presentes].isna().any(axis=1)
        _rejeitar(mask_sem_chave, "equip_id_ou_data_hora_ausente")

    # 2) Duplicatas exatas (todas as colunas) ------------------------------------
    antes = len(trabalho)
    trabalho = trabalho.drop_duplicates(keep="first")
    duplicatas_exatas = antes - len(trabalho)

    # 3) Duplicatas pela chave de negócio (equip_id, data_hora) ------------------
    duplicatas_chave = 0
    if len(chave_presentes) == len(COLUNAS_CHAVE):
        antes = len(trabalho)
        trabalho = trabalho.drop_duplicates(subset=COLUNAS_CHAVE, keep="first")
        duplicatas_chave = antes - len(trabalho)

    # 4) Categorias inválidas (valor presente mas fora do domínio conhecido) ----
    for col, validos in CATEGORIAS_VALIDAS.items():
        if col not in trabalho.columns:
            continue
        mask_invalida = trabalho[col].notna() & ~trabalho[col].isin(validos)
        _rejeitar(mask_invalida, f"{col}_invalido")

    # 5) Categóricas faltantes -> moda --------------------------------------------
    for col in CATEGORIAS_VALIDAS:
        if col not in trabalho.columns:
            continue
        if trabalho[col].isna().any() and trabalho[col].notna().any():
            moda = trabalho[col].mode(dropna=True).iloc[0]
            trabalho[col] = trabalho[col].fillna(moda)

    # 6) Numéricas faltantes -> mediana por tipo_equip (fallback: mediana global) -
    faltantes_preenchidos: dict[str, int] = {}
    for col in RANGES:
        if col not in trabalho.columns:
            continue
        n_faltantes = int(trabalho[col].isna().sum())
        if n_faltantes == 0:
            continue
        if "tipo_equip" in trabalho.columns:
            medianas_grupo = trabalho.groupby("tipo_equip")[col].transform("median")
            trabalho[col] = trabalho[col].fillna(medianas_grupo)
        mediana_global = trabalho[col].median()
        trabalho[col] = trabalho[col].fillna(mediana_global)
        faltantes_preenchidos[col] = n_faltantes

    # 7) Fora de faixa -> clipagem (ou erro em modo estrito) ----------------------
    valores_clipados: dict[str, int] = {}
    colunas_fora_estrito: list[str] = []
    for col, (minimo, maximo) in RANGES.items():
        if col not in trabalho.columns:
            continue
        mask_fora = trabalho[col].notna() & ((trabalho[col] < minimo) | (trabalho[col] > maximo))
        n_fora = int(mask_fora.sum())
        if n_fora == 0:
            continue
        if estrito:
            colunas_fora_estrito.append(col)
            continue
        trabalho[col] = trabalho[col].clip(lower=minimo, upper=maximo)
        valores_clipados[col] = n_fora

    if estrito and colunas_fora_estrito:
        raise DadosInvalidos(
            "Valores fora da faixa esperada em modo estrito: "
            + ", ".join(colunas_fora_estrito)
        )

    if trabalho.empty:
        raise DadosInvalidos("Nenhuma linha válida restou após a preparação dos dados.")

    relatorio = {
        "linhas_entrada": int(linhas_entrada),
        "linhas_saida": int(len(trabalho)),
        "duplicatas_exatas": int(duplicatas_exatas),
        "duplicatas_chave": int(duplicatas_chave),
        "faltantes_preenchidos": faltantes_preenchidos,
        "valores_clipados": valores_clipados,
        "rejeitadas": int(rejeitadas_total),
        "motivos": motivos,
    }
    return trabalho.reset_index(drop=True), relatorio
