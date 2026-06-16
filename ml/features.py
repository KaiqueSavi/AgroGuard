"""
AgroGuard IA — Contrato de Features (Sprint 2)
==============================================

Fonte ÚNICA da verdade sobre quais colunas entram nos modelos. Importado por
train.py, predict.py e eda.py para garantir consistência (evita drift entre
treino e inferência).

Decisão anti-vazamento (data leakage):
  - As colunas-alvo e suas derivadas NÃO entram em X.
  - latitude/longitude ficam FORA do modelo (são identificadores geográficos
    quase únicos → memorização), mas permanecem no banco/dashboard para o mapa.
"""
from __future__ import annotations

# Features numéricas (telemetria + ambiente + operação + equipamento)
NUMERIC_FEATURES = [
    "idade_equipamento_anos",
    "velocidade_kmh",
    "inclinacao_graus",
    "vibracao_g",
    "precip_24h_mm",
    "precip_prev_6h_mm",
    "umidade_solo",
    "vento_max_kmh",
    "dist_corpo_dagua_m",
    "declividade_pct",
    "jornada_acumulada_h",
    "dias_desde_manutencao",
    "experiencia_operador_anos",
]

# Features categóricas (one-hot no pipeline)
CATEGORICAL_FEATURES = [
    "tipo_equip",
    "tipo_operacao",
    "turno",
]

FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Alvos supervisionados
TARGET_CLASSE = "classe_risco"   # classificação multiclasse (principal)
TARGET_SCORE = "risco_score"     # regressão 0-100
TARGET_SINISTRO = "sinistro"     # classificação binária (análise complementar)

# Ordem canônica das classes (do menor para o maior risco)
CLASSES_ORDER = ["Baixo", "Medio", "Alto", "Critico"]

# Limiar de alerta sobre o score (dispara notificação preventiva)
ALERT_THRESHOLD = 80

# Versão do modelo registrada junto aos scores persistidos
MODEL_VERSION = "v0.2"
