# 📖 Dicionário de Dados — AgroGuard IA

> Descrição completa de cada variável do `synthetic_dataset.csv`.
> Total: **26 colunas**, **10.000 registros** simulados.

---

## Sumário das colunas

| # | Coluna | Tipo | Categoria |
|---|---|---|---|
| 1 | `id` | int | Identificador |
| 2 | `data_hora` | datetime | Temporal |
| 3 | `equip_id` | string | Equipamento |
| 4 | `tipo_equip` | categórica | Equipamento |
| 5 | `idade_equipamento_anos` | int | Equipamento |
| 6 | `latitude` | float | Geográfica |
| 7 | `longitude` | float | Geográfica |
| 8 | `velocidade_kmh` | float | Telemetria |
| 9 | `inclinacao_graus` | float | Telemetria |
| 10 | `vibracao_g` | float | Telemetria |
| 11 | `precip_24h_mm` | float | Clima |
| 12 | `precip_prev_6h_mm` | float | Clima |
| 13 | `umidade_solo` | float | Clima/Solo |
| 14 | `vento_max_kmh` | float | Clima |
| 15 | `dist_corpo_dagua_m` | int | Geográfica |
| 16 | `declividade_pct` | float | Geográfica |
| 17 | `tipo_operacao` | categórica | Operação |
| 18 | `turno` | categórica | Operação |
| 19 | `jornada_acumulada_h` | float | Operação |
| 20 | `dias_desde_manutencao` | int | Equipamento |
| 21 | `experiencia_operador_anos` | int | Operação |
| 22 | `risco_score` | int | **Target** |
| 23 | `classe_risco` | categórica | **Target** |
| 24 | `sinistro` | int (0/1) | **Target** |
| 25 | `tipo_sinistro` | categórica | **Target** |
| 26 | `severidade_sinistro` | categórica | **Target** |

---

## Detalhamento

### 1. `id`
- **Tipo:** int
- **Descrição:** Identificador único do registro (1 a N).
- **Fonte:** Sistema (auto-incremento).
- **Exemplo:** `1`, `2`, ..., `10000`

### 2. `data_hora`
- **Tipo:** datetime (`YYYY-MM-DD HH:MM:SS`)
- **Descrição:** Instante em que a leitura foi registrada.
- **Faixa simulada:** 2026-01-01 a 2026-04-30 (janela de safra).
- **Fonte:** Telemetria IoT.
- **Exemplo:** `2026-03-12 14:30:00`

### 3. `equip_id`
- **Tipo:** string
- **Descrição:** Identificador único do equipamento na frota.
- **Padrão:** `EQ-XXX` (50 equipamentos no pool).
- **Fonte:** Cadastro interno.
- **Exemplo:** `EQ-014`

### 4. `tipo_equip`
- **Tipo:** categórica
- **Valores possíveis:** `Colheitadeira`, `Trator`, `Pulverizador`, `Caminhão`
- **Descrição:** Categoria do equipamento.
- **Fonte:** Cadastro interno.

### 5. `idade_equipamento_anos`
- **Tipo:** int
- **Faixa:** 1 a 15
- **Descrição:** Idade do equipamento em anos.
- **Fonte:** Cadastro interno.
- **Por que importa:** equipamentos mais velhos têm maior risco mecânico.

### 6. `latitude`
- **Tipo:** float
- **Faixa:** ~-12.6 a -12.3 (região de Sorriso/MT, simulada)
- **Descrição:** Latitude da posição do equipamento.
- **Fonte:** GPS embarcado.

### 7. `longitude`
- **Tipo:** float
- **Faixa:** ~-55.4 a -55.0
- **Descrição:** Longitude da posição do equipamento.
- **Fonte:** GPS embarcado.

### 8. `velocidade_kmh`
- **Tipo:** float
- **Faixa típica:** 0 a 90 (varia por tipo de equipamento)
- **Descrição:** Velocidade instantânea.
- **Fonte:** Telemetria IoT.

### 9. `inclinacao_graus`
- **Tipo:** float
- **Faixa:** 0 a 8
- **Descrição:** Inclinação do equipamento medida pelo giroscópio.
- **Fonte:** Sensor IoT.
- **Por que importa:** acima de 5° aumenta risco de tombamento.

### 10. `vibracao_g`
- **Tipo:** float
- **Faixa:** 0.2 a 1.8
- **Descrição:** Vibração média (em "g") detectada pelo acelerômetro.
- **Fonte:** Sensor IoT.
- **Por que importa:** vibração alta sugere problema mecânico.

### 11. `precip_24h_mm`
- **Tipo:** float
- **Faixa:** 0 a ~80
- **Descrição:** Precipitação acumulada nas últimas 24 horas, em mm.
- **Fonte:** API OpenWeather/INMET (estação mais próxima).

### 12. `precip_prev_6h_mm`
- **Tipo:** float
- **Faixa:** 0 a ~30
- **Descrição:** Precipitação prevista para as próximas 6 horas, em mm.
- **Fonte:** API de previsão.

### 13. `umidade_solo`
- **Tipo:** float (0 a 1)
- **Descrição:** Umidade volumétrica estimada do solo.
- **Fonte:** Calculada a partir de `precip_24h_mm` + tipo de solo (modelo simplificado).
- **Por que importa:** acima de 0.7 indica solo encharcado, alto risco de atolamento.

### 14. `vento_max_kmh`
- **Tipo:** float
- **Faixa:** 0 a ~80
- **Descrição:** Velocidade máxima do vento prevista para a janela.
- **Fonte:** API meteorológica.

### 15. `dist_corpo_dagua_m`
- **Tipo:** int
- **Faixa:** 5 a 5.000 metros
- **Descrição:** Distância em metros até o corpo d'água mais próximo (rio, córrego, açude).
- **Fonte:** Base hidrográfica do MapBiomas / ANA.

### 16. `declividade_pct`
- **Tipo:** float
- **Faixa:** 0 a 15 (%)
- **Descrição:** Declividade média do terreno na coordenada (% de inclinação).
- **Fonte:** Modelo Digital de Elevação (SRTM / EMBRAPA).

### 17. `tipo_operacao`
- **Tipo:** categórica
- **Valores possíveis:** `campo`, `transporte`, `parado`
- **Descrição:** Tipo de atividade no momento.
- **Fonte:** Telemetria + regras (velocidade alta + asfalto = transporte).

### 18. `turno`
- **Tipo:** categórica
- **Valores:** `manha` (5h-12h), `tarde` (12h-18h), `noite` (18h-5h)
- **Descrição:** Turno do dia.
- **Fonte:** Derivada de `data_hora`.

### 19. `jornada_acumulada_h`
- **Tipo:** float
- **Faixa:** 0 a 14 horas
- **Descrição:** Horas trabalhadas pelo operador no dia.
- **Fonte:** Cálculo a partir do horímetro + ponto eletrônico.

### 20. `dias_desde_manutencao`
- **Tipo:** int
- **Faixa:** 0 a 90 dias
- **Descrição:** Dias desde a última manutenção preventiva.
- **Fonte:** ERP de manutenção.

### 21. `experiencia_operador_anos`
- **Tipo:** int
- **Faixa:** 0 a 30 anos
- **Descrição:** Experiência do operador (anos de carteira como operador).
- **Fonte:** Cadastro de RH / cooperativa.

### 22. `risco_score` ⭐ **TARGET**
- **Tipo:** int
- **Faixa:** 0 a 100
- **Descrição:** Score de risco previsto pelo modelo. Quanto maior, mais alta a probabilidade de incidente nas próximas horas.
- **Geração no dataset simulado:** combinação ponderada de fatores ambientais, operacionais e de equipamento + ruído gaussiano.

### 23. `classe_risco` ⭐ **TARGET**
- **Tipo:** categórica
- **Valores:** `Baixo` (0–30), `Medio` (31–60), `Alto` (61–80), `Critico` (81–100)
- **Descrição:** Classificação categórica derivada do score.

### 24. `sinistro` ⭐ **TARGET**
- **Tipo:** int (0 ou 1)
- **Descrição:** Houve sinistro real associado a este registro?
- **Probabilidade:** proporcional a `risco_score^2.2`.

### 25. `tipo_sinistro`
- **Tipo:** categórica (vazio quando `sinistro = 0`)
- **Valores:** `atolamento`, `colisao`, `tombamento`, `mecanico`
- **Descrição:** Categoria do incidente.

### 26. `severidade_sinistro`
- **Tipo:** categórica (vazio quando `sinistro = 0`)
- **Valores:** `leve`, `moderado`, `grave`, `perda_total`
- **Descrição:** Gravidade do sinistro.

---

## Observações sobre o dataset

- **Distribuição típica gerada (seed=42):**
  - Baixo: ~55% | Médio: ~39% | Alto: ~5% | Crítico: ~0.4%
  - Taxa de sinistros: ~10–11%
- **Desbalanceamento intencional** — reflete a realidade (eventos críticos são raros). Modelos precisarão lidar com isso (SMOTE, class_weight, threshold tuning).
- **Reprodutibilidade:** rodar `python data/generate_dataset.py --seed 42` reproduz o dataset bit-a-bit.
- **Limitações:** dados sintéticos. Não capturam totalmente sazonalidade plurianual nem padrões regionais específicos. Na Sprint 2, faremos validação cruzada com bases reais quando disponíveis.

---

## Exemplo de registro

```json
{
  "id": 4,
  "data_hora": "2026-03-12 14:30:00",
  "equip_id": "EQ-014",
  "tipo_equip": "Colheitadeira",
  "idade_equipamento_anos": 8,
  "latitude": -12.44231,
  "longitude": -55.21044,
  "velocidade_kmh": 5.0,
  "inclinacao_graus": 5.8,
  "vibracao_g": 1.40,
  "precip_24h_mm": 55.0,
  "precip_prev_6h_mm": 12.0,
  "umidade_solo": 0.88,
  "vento_max_kmh": 22.0,
  "dist_corpo_dagua_m": 40,
  "declividade_pct": 6.5,
  "tipo_operacao": "campo",
  "turno": "tarde",
  "jornada_acumulada_h": 8.5,
  "dias_desde_manutencao": 12,
  "experiencia_operador_anos": 6,
  "risco_score": 94,
  "classe_risco": "Critico",
  "sinistro": 1,
  "tipo_sinistro": "atolamento",
  "severidade_sinistro": "grave"
}
```
