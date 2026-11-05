#!/usr/bin/env python3
"""
Relatório Atmosférico, Marítimo, de Marés e Análise de Bodyboard (via Ollama)
para Vila do Conde, Portugal.
Utiliza as APIs gratuitas (sem chave) da Open-Meteo (Weather & Marine)
e o modelo local ministral-3:3b via Ollama.
Sem dependências externas (apenas biblioteca padrão do Python 3).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Coordenadas de Vila do Conde, Portugal
LOCATION_NAME = "Vila do Conde, Portugal"
LATITUDE = 41.3536
LONGITUDE = -8.7439
# Ponto costeiro ligeiramente ao largo da foz do Ave / Vila do Conde para a grelha marítima
MARINE_LATITUDE = 41.3500
MARINE_LONGITUDE = -8.7650
TIMEZONE = "Europe/Lisbon"

# Diferença entre o Nível Médio do Mar (MSL) e o Zero Hidrográfico (ZH) na costa norte (Leixões/Vila do Conde)
# O Nível Médio (NM) situa-se a +2.00 m acima do Zero Hidrográfico (ZH).
ZH_OFFSET_METERS = 2.00

WEATHER_API_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_API_URL = "https://marine-api.open-meteo.com/v1/marine"

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "ministral-3:3b")
BODYBOARD_ANALYSIS_DAYS = 3


class Ansi:
    """Códigos ANSI básicos para formatação no terminal."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.RESET = "\033[0m" if enabled else ""
        self.BOLD = "\033[1m" if enabled else ""
        self.DIM = "\033[2m" if enabled else ""
        self.CYAN = "\033[36m" if enabled else ""
        self.BLUE = "\033[34m" if enabled else ""
        self.GREEN = "\033[32m" if enabled else ""
        self.YELLOW = "\033[33m" if enabled else ""
        self.RED = "\033[31m" if enabled else ""
        self.MAGENTA = "\033[35m" if enabled else ""


WMO_WEATHER_CODES: dict[int, str] = {
    0: "Céu limpo",
    1: "Geralmente limpo",
    2: "Parcialmente nublado",
    3: "Nublado / Encoberto",
    45: "Nevoeiro",
    48: "Nevoeiro com geada",
    51: "Chuvisco fraco",
    53: "Chuvisco moderado",
    55: "Chuvisco denso",
    56: "Chuvisco gelado fraco",
    57: "Chuvisco gelado denso",
    61: "Chuva fraca",
    63: "Chuva moderada",
    65: "Chuva forte",
    66: "Chuva gelada fraca",
    67: "Chuva gelada forte",
    71: "Queda de neve fraca",
    73: "Queda de neve moderada",
    75: "Queda de neve forte",
    77: "Grãos de neve",
    80: "Aguaceiros fracos",
    81: "Aguaceiros moderados",
    82: "Aguaceiros fortes/violentos",
    85: "Aguaceiros de neve fracos",
    86: "Aguaceiros de neve fortes",
    95: "Trovoada",
    96: "Trovoada com granizo fraco",
    99: "Trovoada com granizo forte",
}

DIAS_SEMANA = [
    "Segunda-feira",
    "Terça-feira",
    "Quarta-feira",
    "Quinta-feira",
    "Sexta-feira",
    "Sábado",
    "Domingo",
]


def degrees_to_cardinal(deg: float | None) -> str:
    """Converte graus azimutais (0-360) em ponto cardeal/colateral em português."""
    if deg is None:
        return "N/D"
    directions = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSO", "SO", "OSO",
        "O", "ONO", "NO", "NNO",
    ]
    idx = round(deg / 22.5) % 16
    return f"{directions[idx]} ({deg:.0f}°)"


def classify_wind_for_coast(deg: float | None, speed_kmh: float | None) -> str:
    """
    Classifica o vento para as praias de Vila do Conde (orientadas a Oeste ~270°).
    - Quadrante Este (35° a 145°): Offshore / Terral (alisado, excelente para tubos)
    - Vento < 8 km/h: Fraco / Glassy
    - Quadrante Norte/Sul (335°-35° ou 145°-205°): Side-shore (cruzado)
    - Quadrante Oeste (205° a 335°): Onshore / Marítimo
    """
    if speed_kmh is not None and speed_kmh < 8.0:
        return "Fraco/Glassy (Excelente)"
    if deg is None:
        return "N/D"
    d = deg % 360
    if 35 <= d <= 145:
        return "Offshore / Terral (Ideal)"
    if (145 < d <= 185) or (15 <= d < 35):
        return "Side-offshore (Favorável)"
    if (185 < d <= 215) or (330 <= d or d < 15):
        return "Side-shore / Cruzado"
    return "Onshore / Marítimo (Desfavorável)"


def weather_description(code: int | None) -> str:
    """Devolve a descrição em português do código meteorológico WMO."""
    if code is None:
        return "Desconhecido"
    return WMO_WEATHER_CODES.get(int(code), f"Código WMO {code}")


def fetch_json(base_url: str, params: dict[str, Any], timeout: int = 12) -> dict[str, Any]:
    """Faz um pedido HTTP GET e devolve o JSON descodificado."""
    query = urllib.parse.urlencode(params)
    url = f"{base_url}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "VilaDoConde-Mares-CLI/1.0 (Python urllib)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_weather_data(forecast_days: int = 5) -> dict[str, Any]:
    """Obtém dados meteorológicos atuais, horários e diários para Vila do Conde."""
    days_to_fetch = max(forecast_days, BODYBOARD_ANALYSIS_DAYS)
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "timezone": TIMEZONE,
        "forecast_days": days_to_fetch,
        "current": ",".join([
            "temperature_2m",
            "apparent_temperature",
            "relative_humidity_2m",
            "precipitation",
            "weather_code",
            "cloud_cover",
            "pressure_msl",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_gusts_10m",
            "uv_index",
        ]),
        "hourly": ",".join([
            "temperature_2m",
            "precipitation",
            "weather_code",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_gusts_10m",
        ]),
        "daily": ",".join([
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "sunrise",
            "sunset",
            "uv_index_max",
            "precipitation_sum",
            "precipitation_probability_max",
            "wind_speed_10m_max",
            "wind_gusts_10m_max",
            "wind_direction_10m_dominant",
        ]),
    }
    return fetch_json(WEATHER_API_URL, params)


def fetch_marine_data(forecast_days: int = 5) -> dict[str, Any]:
    """Obtém dados marítimos e de nível do mar (marés) para Vila do Conde."""
    days_to_fetch = max(forecast_days, BODYBOARD_ANALYSIS_DAYS)
    params = {
        "latitude": MARINE_LATITUDE,
        "longitude": MARINE_LONGITUDE,
        "timezone": TIMEZONE,
        "past_days": 1,
        "forecast_days": days_to_fetch,
        "current": ",".join([
            "wave_height",
            "wave_direction",
            "wave_period",
            "swell_wave_height",
            "swell_wave_direction",
            "swell_wave_period",
            "wind_wave_height",
            "sea_surface_temperature",
            "sea_level_height_msl",
        ]),
        "hourly": ",".join([
            "sea_level_height_msl",
            "wave_height",
            "wave_period",
            "wave_direction",
            "swell_wave_height",
            "swell_wave_period",
            "swell_wave_direction",
            "wind_wave_height",
            "sea_surface_temperature",
        ]),
        "daily": ",".join([
            "wave_height_max",
            "wave_direction_dominant",
            "wave_period_max",
            "swell_wave_height_max",
            "swell_wave_period_max",
        ]),
    }
    return fetch_json(MARINE_API_URL, params)


def extract_tides_from_hourly(
    times_iso: list[str],
    levels_msl: list[float | None],
) -> list[dict[str, Any]]:
    """
    Identifica os extremos de maré (Preia-mar e Baixa-mar) a partir de séries horárias
    de `sea_level_height_msl` usando interpolação parabólica nos 3 pontos em torno de
    cada extremo para obter o minuto exato e a altura refinada.
    """
    valid_points: list[tuple[datetime, float]] = []
    for t_str, lvl in zip(times_iso, levels_msl):
        if lvl is not None:
            valid_points.append((datetime.fromisoformat(t_str), float(lvl)))

    if len(valid_points) < 5:
        return []

    extrema: list[dict[str, Any]] = []
    n = len(valid_points)

    for i in range(2, n - 2):
        t_prev, y_prev = valid_points[i - 1]
        t_curr, y_curr = valid_points[i]
        t_next, y_next = valid_points[i + 1]
        _, y_prev2 = valid_points[i - 2]
        _, y_next2 = valid_points[i + 2]

        # Verifica se é um máximo local (Preia-mar) ou mínimo local (Baixa-mar)
        # num intervalo de ±2 horas (ciclo semidiurno tem ~6h12m entre extremos)
        is_max = (
            y_curr >= y_prev
            and y_curr > y_next
            and y_curr >= y_prev2
            and y_curr >= y_next2
        )
        is_min = (
            y_curr <= y_prev
            and y_curr < y_next
            and y_curr <= y_prev2
            and y_curr <= y_next2
        )

        if not (is_max or is_min):
            continue

        # Evita duplicados demasiado próximos (< 4 horas)
        if extrema and abs((t_curr - extrema[-1]["raw_time"]).total_seconds()) < 4 * 3600:
            last = extrema[-1]
            if (is_max and last["type"] == "HIGH" and y_curr > last["height_msl"]) or (
                is_min and last["type"] == "LOW" and y_curr < last["height_msl"]
            ):
                extrema.pop()
            else:
                continue

        # Interpolação parabólica nos pontos (i-1, i, i+1)
        denom = 2.0 * (y_prev - 2.0 * y_curr + y_next)
        if abs(denom) > 1e-6:
            delta_hours = (y_prev - y_next) / denom
            delta_hours = max(-0.75, min(0.75, delta_hours))
            y_interp = y_curr - ((y_prev - y_next) ** 2) / (4.0 * denom)
        else:
            delta_hours = 0.0
            y_interp = y_curr

        exact_time = t_curr + timedelta(hours=delta_hours)
        height_zh = y_interp + ZH_OFFSET_METERS

        extrema.append({
            "type": "HIGH" if is_max else "LOW",
            "label": "Preia-mar" if is_max else "Baixa-mar",
            "time": exact_time,
            "raw_time": t_curr,
            "height_msl": round(y_interp, 2),
            "height_zh": round(height_zh, 2),
        })

    return extrema


def compute_current_tide_state(
    now: datetime,
    tides: list[dict[str, Any]],
    current_msl: float | None,
) -> dict[str, Any] | None:
    """Determina se a maré está a encher ou a vazar e o progresso entre extremos."""
    if not tides:
        return None

    prev_tide = None
    next_tide = None
    for tide in tides:
        if tide["time"] <= now:
            prev_tide = tide
        elif tide["time"] > now and next_tide is None:
            next_tide = tide
            break

    if next_tide is None:
        return None

    rising = next_tide["type"] == "HIGH"
    status_str = "A ENCHER ↗" if rising else "A VAZAR ↘"

    progress = None
    estimated_zh = (current_msl + ZH_OFFSET_METERS) if current_msl is not None else None

    if prev_tide is not None:
        total_sec = (next_tide["time"] - prev_tide["time"]).total_seconds()
        elapsed_sec = (now - prev_tide["time"]).total_seconds()
        if total_sec > 0:
            progress = max(0.0, min(1.0, elapsed_sec / total_sec))
            if estimated_zh is None:
                factor = (1.0 - math.cos(math.pi * progress)) / 2.0
                estimated_zh = prev_tide["height_zh"] + factor * (
                    next_tide["height_zh"] - prev_tide["height_zh"]
                )

    remaining = next_tide["time"] - now
    rem_total_minutes = max(0, int(remaining.total_seconds() // 60))
    rem_hours, rem_minutes = divmod(rem_total_minutes, 60)

    return {
        "status": status_str,
        "rising": rising,
        "prev_tide": prev_tide,
        "next_tide": next_tide,
        "progress": progress,
        "estimated_zh": round(estimated_zh, 2) if estimated_zh is not None else None,
        "remaining_str": f"{rem_hours}h {rem_minutes:02d}m" if rem_hours > 0 else f"{rem_minutes}m",
    }


def build_3day_bodyboard_context(
    weather: dict[str, Any],
    marine: dict[str, Any],
    tides: list[dict[str, Any]],
) -> str:
    """
    Constrói um resumo estruturado dos próximos 3 dias (em janelas diurnas de 3h + marés)
    otimizado para ser analisado pelo modelo ministral-3:3b no Ollama.
    """
    curr_w = weather.get("current", {})
    curr_m = marine.get("current", {})
    now_str = curr_w.get("time") or datetime.now().strftime("%Y-%m-%dT%H:%M")
    now_dt = datetime.fromisoformat(now_str)

    hourly_w = weather.get("hourly", {})
    hourly_m = marine.get("hourly", {})
    daily_w = weather.get("daily", {})

    # Indexar séries horárias por timestamp "YYYY-MM-DDTHH:MM"
    w_by_time: dict[str, dict[str, Any]] = {}
    for idx, t_str in enumerate(hourly_w.get("time", [])):
        w_by_time[t_str] = {
            "temp": _safe_idx(hourly_w.get("temperature_2m"), idx),
            "precip": _safe_idx(hourly_w.get("precipitation"), idx),
            "wcode": _safe_idx(hourly_w.get("weather_code"), idx),
            "wind_spd": _safe_idx(hourly_w.get("wind_speed_10m"), idx),
            "wind_dir": _safe_idx(hourly_w.get("wind_direction_10m"), idx),
            "wind_gst": _safe_idx(hourly_w.get("wind_gusts_10m"), idx),
        }

    m_by_time: dict[str, dict[str, Any]] = {}
    for idx, t_str in enumerate(hourly_m.get("time", [])):
        msl = _safe_idx(hourly_m.get("sea_level_height_msl"), idx)
        m_by_time[t_str] = {
            "wave_h": _safe_idx(hourly_m.get("wave_height"), idx),
            "wave_p": _safe_idx(hourly_m.get("wave_period"), idx),
            "wave_d": _safe_idx(hourly_m.get("wave_direction"), idx),
            "swell_h": _safe_idx(hourly_m.get("swell_wave_height"), idx),
            "swell_p": _safe_idx(hourly_m.get("swell_wave_period"), idx),
            "swell_d": _safe_idx(hourly_m.get("swell_wave_direction"), idx),
            "wind_wave_h": _safe_idx(hourly_m.get("wind_wave_height"), idx),
            "sst": _safe_idx(hourly_m.get("sea_surface_temperature"), idx),
            "zh": round(msl + ZH_OFFSET_METERS, 2) if msl is not None else None,
        }

    lines: list[str] = []
    lines.append(f"Localização: {LOCATION_NAME} (Praias orientadas a Oeste ~270°)")
    lines.append(f"Data/Hora da recolha: {now_dt.strftime('%d/%m/%Y %H:%M')}")
    sst_now = curr_m.get("sea_surface_temperature", "N/D")
    lines.append(f"Temperatura atual da água do mar: {sst_now} °C")
    lines.append("")

    d_times = daily_w.get("time", [])[:BODYBOARD_ANALYSIS_DAYS]
    sample_hours = [7, 10, 13, 16, 18]

    for i, d_str in enumerate(d_times):
        d_dt = datetime.fromisoformat(d_str)
        sunrise = (_safe_idx(daily_w.get("sunrise"), i) or "07:00")[-5:]
        sunset = (_safe_idx(daily_w.get("sunset"), i) or "18:00")[-5:]

        lines.append(f"=== DIA {i + 1}: {format_date_pt(d_dt)} (Luz solar: {sunrise} às {sunset}) ===")

        day_tides = [t for t in tides if t["time"].date() == d_dt.date()]
        if day_tides:
            tides_str = " | ".join(
                f"{t['label']} às {t['time'].strftime('%H:%M')} ({t['height_zh']:.2f}m ZH)"
                for t in day_tides
            )
            lines.append(f"Marés do dia: {tides_str}")
        else:
            lines.append("Marés do dia: N/D")

        lines.append("Janelas horárias diurnas:")
        for hr in sample_hours:
            slot_key = f"{d_str}T{hr:02d}:00"
            slot_dt = datetime.fromisoformat(slot_key)
            # Se for no próprio dia e a hora já passou há mais de 2h, indicar como passado
            past_tag = " [JÁ PASSOU]" if slot_dt < (now_dt - timedelta(hours=1)) else ""

            w = w_by_time.get(slot_key, {})
            m = m_by_time.get(slot_key, {})

            t_state = compute_current_tide_state(
                slot_dt,
                tides,
                (m.get("zh") - ZH_OFFSET_METERS) if m.get("zh") is not None else None,
            )
            tide_info = (
                f"{t_state['status']} (~{t_state['estimated_zh']}m ZH)"
                if t_state and t_state.get("estimated_zh") is not None
                else "N/D"
            )

            w_spd = w.get("wind_spd")
            w_gst = w.get("wind_gst")
            w_dir_deg = w.get("wind_dir")
            w_dir_card = degrees_to_cardinal(w_dir_deg)
            w_type = classify_wind_for_coast(w_dir_deg, w_spd)

            wave_h = m.get("wave_h", "N/D")
            swell_h = m.get("swell_h", "N/D")
            swell_p = m.get("swell_p") or m.get("wave_p") or "N/D"
            swell_d = degrees_to_cardinal(m.get("swell_d") or m.get("wave_d"))
            temp = w.get("temp", "N/D")
            precip = w.get("precip", 0.0)

            lines.append(
                f"  - {hr:02d}:00{past_tag}: "
                f"Ondas={wave_h}m (Swell={swell_h}m, Período={swell_p}s, Dir={swell_d}) | "
                f"Vento={w_spd} km/h (Rajadas {w_gst} km/h) de {w_dir_card} [{w_type}] | "
                f"Maré={tide_info} | Ar={temp}°C, Chuva={precip}mm"
            )
        lines.append("")

    return "\n".join(lines)


def query_ollama_bodyboard(
    context_data: str,
    ollama_url: str,
    model: str,
    stream_to_stdout: bool = True,
    timeout: int = 120,
) -> str:
    """
    Envia os dados meteorológicos, de ondulação e marés para o Ollama (`ministral-3:3b`)
    e devolve (ou faz stream em tempo real) a recomendação para bodyboard.
    """
    system_prompt = (
        "És um especialista local em bodyboard e oceanografia em Vila do Conde, Portugal. "
        "Analisa os dados fornecidos para os próximos 3 dias e indica as melhores janelas "
        "horárias para fazer bodyboard.\n\n"
        "Regras técnicas para Bodyboard em Vila do Conde (praias viradas a Oeste):\n"
        "1. VENTO: O fator mais crítico. Vento Offshore/Terral (de E, ENE, ESE, NE, SE) ou "
        "vento fraco (< 10 km/h) alisa o mar e forma tubos perfeitos. Vento Onshore forte "
        "(de O, NO, SO > 18 km/h) estraga a formação da onda.\n"
        "2. ONDULAÇÃO (SWELL): Ideal entre 1.0 m e 2.5 m com período >= 10 segundos (quanto "
        "maior o período, mais força e melhores rampas/tubos). Acima de 3.0 m o mar pode "
        "fechar (closeout) nos fundos de areia.\n"
        "3. MARÉ: Meia-maré a encher (ou vazante perto da baixa-mar/meia-maré) costuma "
        "produzir as ondas mais cavadas nos bancos de areia e rocha de Vila do Conde.\n"
        "4. LUZ SOLAR: Recomenda apenas horários diurnos (entre o nascer e o pôr do sol) "
        "que ainda não tenham passado.\n\n"
        "Responde sempre em Português de Portugal, de forma direta, clara e bem estruturada:\n"
        "- 🏆 MELHOR ALTURA (TOP #1): Dia, janela horária exata, condições de ondas/período, "
        "vento, fase da maré e o porquê de ser a melhor sessão.\n"
        "- 🥈 ALTERNATIVAS (TOP #2 e #3): Outras boas janelas nos próximos 3 dias.\n"
        "- 📅 RESUMO DIA A DIA: Breve nota para cada um dos 3 dias.\n"
        "-  wetsuit/equipamento: Recomendação rápida de fato conforme a temperatura da água e do ar."
    )

    user_prompt = (
        "Aqui estão os dados atmosféricos, de ondulação e marés recolhidos para Vila do Conde "
        "nos próximos 3 dias. Qual é a melhor altura para fazer bodyboard?\n\n"
        f"{context_data}"
    )

    endpoint = f"{ollama_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": stream_to_stdout,
        "options": {
            "temperature": 0.3,
        },
    }

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    collected: list[str] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if stream_to_stdout:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                chunk_obj = json.loads(line)
                token = chunk_obj.get("message", {}).get("content", "")
                if token:
                    sys.stdout.write(token)
                    sys.stdout.flush()
                    collected.append(token)
                if chunk_obj.get("done"):
                    break
            sys.stdout.write("\n")
            sys.stdout.flush()
        else:
            body = json.loads(resp.read().decode("utf-8"))
            content = body.get("message", {}).get("content", "")
            collected.append(content)

    return "".join(collected).strip()


def render_progress_bar(progress: float | None, width: int = 20) -> str:
    """Desenha uma barra de progresso simples em texto."""
    if progress is None:
        return ""
    filled = round(progress * width)
    empty = width - filled
    pct = round(progress * 100)
    return f"[{'#' * filled}{'-' * empty}] {pct}%"


def format_date_pt(dt_date: datetime) -> str:
    """Formata uma data em português (ex: Quinta-feira, 05/11/2026)."""
    weekday = DIAS_SEMANA[dt_date.weekday()]
    return f"{weekday}, {dt_date.strftime('%d/%m/%Y')}"


def print_report(
    weather: dict[str, Any],
    marine: dict[str, Any],
    tides: list[dict[str, Any]],
    forecast_days: int,
    c: Ansi,
) -> None:
    """Imprime o relatório completo no terminal."""
    curr_w = weather.get("current", {})
    curr_m = marine.get("current", {})

    now_str = curr_w.get("time") or datetime.now().strftime("%Y-%m-%dT%H:%M")
    now_dt = datetime.fromisoformat(now_str)

    sep_heavy = "=" * 74
    sep_light = "-" * 74

    print(f"{c.BOLD}{c.CYAN}{sep_heavy}{c.RESET}")
    print(
        f"{c.BOLD}  RELATÓRIO ATMOSFÉRICO, MARÍTIMO E DE MARÉS — {LOCATION_NAME.upper()}{c.RESET}"
    )
    print(
        f"  Coordenadas: {LATITUDE:.4f}°N, {abs(LONGITUDE):.4f}°O  |  "
        f"Atualizado: {now_dt.strftime('%d/%m/%Y %H:%M')} ({TIMEZONE})"
    )
    print(f"{c.BOLD}{c.CYAN}{sep_heavy}{c.RESET}\n")

    # 1. CONDIÇÕES ATMOSFÉRICAS ATUAIS
    print(f"{c.BOLD}{c.YELLOW}[1] METEOROLOGIA ATUAL{c.RESET}")
    print(sep_light)
    w_desc = weather_description(curr_w.get("weather_code"))
    temp = curr_w.get("temperature_2m", "N/D")
    feels = curr_w.get("apparent_temperature", "N/D")
    hum = curr_w.get("relative_humidity_2m", "N/D")
    press = curr_w.get("pressure_msl", "N/D")
    clouds = curr_w.get("cloud_cover", "N/D")
    precip = curr_w.get("precipitation", 0.0)
    uv = curr_w.get("uv_index", "N/D")
    wind_spd = curr_w.get("wind_speed_10m", "N/D")
    wind_gst = curr_w.get("wind_gusts_10m", "N/D")
    wind_dir = degrees_to_cardinal(curr_w.get("wind_direction_10m"))

    print(f"  Estado do Céu      : {c.BOLD}{w_desc}{c.RESET} (Nebulosidade: {clouds}%)")
    print(f"  Temperatura        : {c.BOLD}{temp} °C{c.RESET} (Sensação térmica: {feels} °C)")
    print(f"  Vento (10m)        : {wind_spd} km/h de {wind_dir} (Rajadas: {wind_gst} km/h)")
    print(f"  Humidade Relativa  : {hum}%   |   Pressão Atmosférica: {press} hPa")
    print(f"  Precipitação atual : {precip} mm  |   Índice UV atual    : {uv}")
    print()

    # 2. ESTADO DO MAR ATUAL
    print(f"{c.BOLD}{c.BLUE}[2] ESTADO DO MAR ATUAL (COSTA DE VILA DO CONDE){c.RESET}")
    print(sep_light)
    wave_h = curr_m.get("wave_height")
    wave_p = curr_m.get("wave_period")
    wave_d = degrees_to_cardinal(curr_m.get("wave_direction"))
    swell_h = curr_m.get("swell_wave_height")
    swell_p = curr_m.get("swell_wave_period")
    swell_d = degrees_to_cardinal(curr_m.get("swell_wave_direction"))
    wind_wave_h = curr_m.get("wind_wave_height")
    sst = curr_m.get("sea_surface_temperature")

    print(
        f"  Ondulação Total    : {c.BOLD}{wave_h if wave_h is not None else 'N/D'} m{c.RESET} "
        f"| Período: {wave_p if wave_p is not None else 'N/D'} s | Direção: {wave_d}"
    )
    print(
        f"  Swell (Fundo)      : {swell_h if swell_h is not None else 'N/D'} m "
        f"| Período: {swell_p if swell_p is not None else 'N/D'} s | Direção: {swell_d}"
    )
    print(
        f"  Vaga de Vento      : {wind_wave_h if wind_wave_h is not None else 'N/D'} m   |   "
        f"Temp. da Água: {c.BOLD}{sst if sst is not None else 'N/D'} °C{c.RESET}"
    )
    print()

    # 3. ESTADO ATUAL E PRÓXIMAS MARÉS (HOJE E AMANHÃ)
    print(f"{c.BOLD}{c.GREEN}[3] TÁBUA DE MARÉS — HOJE E AMANHÃ{c.RESET}")
    print(sep_light)

    tide_state = compute_current_tide_state(
        now_dt,
        tides,
        curr_m.get("sea_level_height_msl"),
    )
    if tide_state:
        nxt = tide_state["next_tide"]
        bar = render_progress_bar(tide_state["progress"])
        zh_now = (
            f"{tide_state['estimated_zh']:.2f} m (ZH)"
            if tide_state["estimated_zh"] is not None
            else "N/D"
        )
        print(
            f"  Estado Atual       : {c.BOLD}{tide_state['status']}{c.RESET} {bar}"
        )
        print(
            f"  Altura Estimada    : ~{zh_now}  |  "
            f"Próxima: {c.BOLD}{nxt['label']}{c.RESET} às {c.BOLD}{nxt['time'].strftime('%H:%M')}{c.RESET} "
            f"(daqui a {tide_state['remaining_str']})"
        )
        print(sep_light)

    today_date = now_dt.date()
    tomorrow_date = today_date + timedelta(days=1)

    for target_date, label_dia in [(today_date, "HOJE"), (tomorrow_date, "AMANHÃ")]:
        day_tides = [t for t in tides if t["time"].date() == target_date]
        dt_obj = datetime.combine(target_date, datetime.min.time())
        print(f"  {c.BOLD}{label_dia} — {format_date_pt(dt_obj)}{c.RESET}")
        if not day_tides:
            print("    Sem dados de marés disponíveis para este dia.")
        else:
            print(f"    {'HORA':<8} {'TIPO DE MARÉ':<15} {'ALTURA (ZH)*':<15} {'MSL':<10} {'ESTADO'}")
            for t in day_tides:
                is_past = t["time"] <= now_dt
                is_next = (
                    tide_state is not None
                    and tide_state["next_tide"]["time"] == t["time"]
                )
                arrow = "▲" if t["type"] == "HIGH" else "▼"
                color = c.CYAN if t["type"] == "HIGH" else c.YELLOW
                if is_next:
                    marker = f"{c.BOLD}{c.GREEN}<-- PRÓXIMA MARÉ{c.RESET}"
                elif is_past:
                    marker = f"{c.DIM}(já ocorreu){c.RESET}"
                else:
                    marker = ""

                print(
                    f"    {c.BOLD}{t['time'].strftime('%H:%M')}{c.RESET}    "
                    f"{color}{arrow} {t['label']:<12}{c.RESET}  "
                    f"{t['height_zh']:>5.2f} m        "
                    f"({t['height_msl']:>+5.2f} m)  {marker}"
                )
        print()

    print(
        f"  {c.DIM}*Nota: Altura (ZH) referenciada ao Zero Hidrográfico (~MSL + {ZH_OFFSET_METERS:.2f} m). "
        f"Valores modelados por Open-Meteo Marine.{c.RESET}\n"
    )

    # 4. PREVISÃO PARA OS PRÓXIMOS DIAS (METEOROLOGIA + MAR + MARÉS)
    daily_w = weather.get("daily", {})
    daily_m = marine.get("daily", {})
    d_times = daily_w.get("time", [])

    marine_by_date: dict[str, dict[str, Any]] = {}
    m_times = daily_m.get("time", [])
    for idx, d_str in enumerate(m_times):
        marine_by_date[d_str] = {
            "wave_max": _safe_idx(daily_m.get("wave_height_max"), idx),
            "wave_period": _safe_idx(daily_m.get("wave_period_max"), idx),
            "wave_dir": _safe_idx(daily_m.get("wave_direction_dominant"), idx),
            "swell_max": _safe_idx(daily_m.get("swell_wave_height_max"), idx),
        }

    num_days = min(forecast_days, len(d_times))
    print(f"{c.BOLD}{c.MAGENTA}[4] PREVISÃO PARA OS PRÓXIMOS {num_days} DIAS{c.RESET}")
    print(sep_light)

    for i in range(num_days):
        d_str = d_times[i]
        d_dt = datetime.fromisoformat(d_str)
        w_code = _safe_idx(daily_w.get("weather_code"), i)
        t_min = _safe_idx(daily_w.get("temperature_2m_min"), i)
        t_max = _safe_idx(daily_w.get("temperature_2m_max"), i)
        p_sum = _safe_idx(daily_w.get("precipitation_sum"), i)
        p_prob = _safe_idx(daily_w.get("precipitation_probability_max"), i)
        w_spd = _safe_idx(daily_w.get("wind_speed_10m_max"), i)
        w_dir = degrees_to_cardinal(_safe_idx(daily_w.get("wind_direction_10m_dominant"), i))
        sunrise = (_safe_idx(daily_w.get("sunrise"), i) or "")[-5:]
        sunset = (_safe_idx(daily_w.get("sunset"), i) or "")[-5:]

        m_info = marine_by_date.get(d_str, {})
        wave_max = m_info.get("wave_max", "N/D")
        wave_per = m_info.get("wave_period", "N/D")
        wave_dir = degrees_to_cardinal(m_info.get("wave_dir"))

        day_tides = [t for t in tides if t["time"].date() == d_dt.date()]
        tides_summary = ", ".join(
            f"{'PM' if t['type'] == 'HIGH' else 'BM'} {t['time'].strftime('%H:%M')} ({t['height_zh']:.1f}m)"
            for t in day_tides
        )

        print(f"  {c.BOLD}▸ {format_date_pt(d_dt)}{c.RESET}  (Sol: {sunrise} - {sunset})")
        print(
            f"    Tempo : {weather_description(w_code)} | "
            f"Temp: {c.BOLD}{t_min}°C a {t_max}°C{c.RESET} | "
            f"Chuva: {p_sum} mm ({p_prob}%)"
        )
        print(
            f"    Vento : Máx {w_spd} km/h de {w_dir} | "
            f"Mar: Ondas máx {c.BOLD}{wave_max} m{c.RESET} ({wave_per} s, {wave_dir})"
        )
        if tides_summary:
            print(f"    Marés : {tides_summary}")
        if i < num_days - 1:
            print()

    print()


def print_ai_analysis_section(
    weather: dict[str, Any],
    marine: dict[str, Any],
    tides: list[dict[str, Any]],
    ollama_url: str,
    model: str,
    c: Ansi,
) -> None:
    """Imprime a secção [5] com a análise de Bodyboard gerada pelo modelo Ollama."""
    sep_heavy = "=" * 74
    sep_light = "-" * 74

    print(
        f"{c.BOLD}{c.CYAN}[5] ANÁLISE DE BODYBOARD (PRÓXIMOS 3 DIAS) — IA ({model}){c.RESET}"
    )
    print(sep_light)

    context_data = build_3day_bodyboard_context(weather, marine, tides)
    try:
        query_ollama_bodyboard(
            context_data=context_data,
            ollama_url=ollama_url,
            model=model,
            stream_to_stdout=True,
        )
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        print(
            f"  {c.RED}Erro HTTP do Ollama ({exc.code}): {err_body}{c.RESET}\n"
            f"  {c.DIM}Verifica se o modelo '{model}' está instalado (`ollama pull {model}`).{c.RESET}",
            file=sys.stderr,
        )
    except urllib.error.URLError as exc:
        print(
            f"  {c.RED}Não foi possível ligar ao Ollama em {ollama_url}: {exc.reason}{c.RESET}\n"
            f"  {c.DIM}Certifica-te de que o serviço Ollama está a correr (`ollama serve`).{c.RESET}",
            file=sys.stderr,
        )
    except Exception as exc:
        print(
            f"  {c.RED}Erro ao consultar o modelo '{model}': {exc}{c.RESET}",
            file=sys.stderr,
        )

    print(f"{c.BOLD}{c.CYAN}{sep_heavy}{c.RESET}")


def _safe_idx(lst: list[Any] | None, idx: int) -> Any:
    if not lst or idx >= len(lst):
        return None
    return lst[idx]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Relatório atmosférico, marítimo, de marés e recomendação de bodyboard "
            "(via Ollama) para Vila do Conde, Portugal."
        )
    )
    parser.add_argument(
        "-d",
        "--days",
        type=int,
        default=5,
        choices=range(1, 8),
        metavar="1..7",
        help="Número de dias de previsão a apresentar (padrão: 5).",
    )
    parser.add_argument(
        "-m",
        "--model",
        default=DEFAULT_OLLAMA_MODEL,
        help=f"Modelo Ollama a utilizar para a análise (padrão: {DEFAULT_OLLAMA_MODEL}).",
    )
    parser.add_argument(
        "--ollama-url",
        default=DEFAULT_OLLAMA_URL,
        help=f"URL base da API do Ollama (padrão: {DEFAULT_OLLAMA_URL}).",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Desativa a análise de bodyboard via Ollama.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Desativa as cores ANSI no output.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Exporta os dados recolhidos, marés e análise em formato JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    use_color = (
        not args.no_color
        and os.environ.get("NO_COLOR") is None
        and sys.stdout.isatty()
    )
    ansi = Ansi(enabled=use_color)

    try:
        weather = fetch_weather_data(forecast_days=args.days)
        marine = fetch_marine_data(forecast_days=args.days)
    except urllib.error.URLError as exc:
        print(
            f"Erro de ligação ao obter dados da Open-Meteo: {exc}",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"Erro inesperado ao processar os dados: {exc}", file=sys.stderr)
        return 1

    hourly_m = marine.get("hourly", {})
    tides = extract_tides_from_hourly(
        hourly_m.get("time", []),
        hourly_m.get("sea_level_height_msl", []),
    )

    if args.json:
        serializable_tides = [
            {
                "type": t["type"],
                "label": t["label"],
                "time": t["time"].strftime("%Y-%m-%dT%H:%M"),
                "height_zh_m": t["height_zh"],
                "height_msl_m": t["height_msl"],
            }
            for t in tides
        ]
        ai_recommendation = None
        if not args.no_ai:
            try:
                ctx = build_3day_bodyboard_context(weather, marine, tides)
                ai_recommendation = query_ollama_bodyboard(
                    context_data=ctx,
                    ollama_url=args.ollama_url,
                    model=args.model,
                    stream_to_stdout=False,
                )
            except Exception as exc:
                ai_recommendation = f"Erro ao consultar Ollama ({args.model}): {exc}"

        print(
            json.dumps(
                {
                    "location": LOCATION_NAME,
                    "coordinates": {"latitude": LATITUDE, "longitude": LONGITUDE},
                    "weather": weather,
                    "marine": {
                        "current": marine.get("current"),
                        "daily": marine.get("daily"),
                    },
                    "tides": serializable_tides,
                    "bodyboard_analysis": {
                        "model": args.model,
                        "recommendation": ai_recommendation,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print_report(weather, marine, tides, args.days, ansi)
    if not args.no_ai:
        print_ai_analysis_section(
            weather=weather,
            marine=marine,
            tides=tides,
            ollama_url=args.ollama_url,
            model=args.model,
            c=ansi,
        )
    else:
        print(f"{ansi.BOLD}{ansi.CYAN}{'=' * 74}{ansi.RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
