# 🌊 Marés & Meteorologia — Vila do Conde (CLI + IA Bodyboard)

Aplicação de linha de comandos (CLI) em Python que recolhe dados atmosféricos, oceanográficos e de marés para **Vila do Conde, Portugal**, e utiliza o modelo local **`ministral-3:3b`** (via **Ollama**) para analisar e recomendar as melhores janelas nos próximos 3 dias para fazer **bodyboard**.

---

## ✨ Funcionalidades

1. **Meteorologia Atual (`Open-Meteo Weather API`)**
   - Estado do céu (códigos WMO traduzidos para português), temperatura real e sensação térmica.
   - Velocidade, rajadas e direção cardeal do vento a 10 metros.
   - Humidade relativa, pressão atmosférica ao nível do mar, precipitação e índice UV.
2. **Estado do Mar Atual (`Open-Meteo Marine API`)**
   - Altura significativa, período e direção da ondulação total.
   - *Swell* (ondulação de fundo), vaga de vento e temperatura da água do mar.
3. **Tábua de Marés (Hoje e Amanhã)**
   - Deteção de **Preia-mar** e **Baixa-mar** com **interpolação parabólica** sobre a série de nível do mar (`sea_level_height_msl`) para obter o minuto exato e a altura refinada.
   - Alturas apresentadas em relação ao **Zero Hidrográfico (ZH)** (`~MSL + 2.00 m` na costa norte portuguesa) e ao **Nível Médio do Mar (MSL)**.
   - Indicador visual do estado atual da maré (`A ENCHER ↗` ou `A VAZAR ↘`), barra de progresso, altura atual estimada e tempo restante até à próxima maré.
4. **Previsão Diária (1 a 7 dias)**
   - Resumo diário de temperaturas, probabilidade/acumulado de chuva, vento máximo, ondulação máxima, nascer/pôr do sol e marés do dia.
5. **Análise de Bodyboard com IA Local (`Ollama` + `ministral-3:3b`)**
   - Classifica automaticamente o vento para a orientação costeira de Vila do Conde (~270° Oeste) em *Offshore / Terral*, *Fraco / Glassy*, *Side-shore* ou *Onshore / Marítimo*.
   - Constrói um resumo estruturado das janelas diurnas (`07h`, `10h`, `13h`, `16h`, `18h`) dos próximos 3 dias e faz *streaming* em tempo real da recomendação do modelo `ministral-3:3b`.

---

## 📋 Pré-requisitos

- **Python 3.10+** (não requer bibliotecas externas via `pip`; usa apenas a biblioteca padrão).
- **[Ollama](https://ollama.com/)** instalado e a correr localmente com o modelo `ministral-3:3b`:
  ```bash
  ollama pull ministral-3:3b
  ollama serve
  ```

---

## 🚀 Utilização

```bash
# Executar o relatório completo + análise de bodyboard via Ollama
python3 mares.py

# Alterar o número de dias da tabela de previsão (1 a 7, padrão: 5)
python3 mares.py --days 3

# Especificar outro modelo ou endereço do servidor Ollama
python3 mares.py --model ministral-3:3b --ollama-url http://localhost:11434

# Executar apenas o relatório meteorológico e de marés (sem consultar o Ollama)
python3 mares.py --no-ai

# Desativar cores ANSI (útil para guardar num ficheiro de texto)
python3 mares.py --no-color > relatorio.txt

# Exportar todos os dados, marés e análise da IA em formato JSON
python3 mares.py --json
```

### Variáveis de Ambiente Suportadas

- `OLLAMA_HOST`: URL base do servidor Ollama (padrão: `http://localhost:11434`).
- `OLLAMA_MODEL`: Nome do modelo a utilizar (padrão: `ministral-3:3b`).
- `NO_COLOR`: Se definida, desativa a formatação com cores ANSI.

