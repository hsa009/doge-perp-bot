import json
import logging

from bot.config import AI_MODELS, GEMINI_MODEL

logger = logging.getLogger(__name__)

ALL_MODEL_IDS = [m.strip() for m in AI_MODELS.split(",") if m.strip()]


def _build_model_keys() -> dict[str, str]:
    seen: dict[str, int] = {}
    keys: dict[str, str] = {}
    for m in ALL_MODEL_IDS:
        short = m.split(":")[-1].replace("-", "").replace(".", "").replace("_", "")
        idx = seen.get(short, 0)
        seen[short] = idx + 1
        key = f"{short}#{idx}"
        keys[key] = m
    return keys


MODELS: dict[str, str] = _build_model_keys()
MODEL_KEYS: list[str] = list(MODELS.keys())


def get_model_defs() -> list[dict]:
    defs = []
    for key, model_id in MODELS.items():
        name = model_id.split(":")[-1]
        defs.append({"key": key, "model_id": model_id, "name": name})
    return defs


def _extract_json(text: str) -> str:
    idx = text.find("{")
    if idx == -1:
        return text
    text = text[idx:]
    depth = 0
    in_string = False
    escaped = False
    end = 0
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == 0:
        return text
    return _clean_json(text[:end])


def _clean_json(s: str) -> str:
    s = s.strip()
    if s.endswith("```"):
        s = s[:-3]
    s = s.strip()
    import re
    s = re.sub(r",\s*}", "}", s)
    s = re.sub(r",\s*]", "]", s)
    return s


def _parse_response(key: str, model: str, name: str, content: str) -> dict | None:
    content = content.strip()
    try:
        parsed = json.loads(content)
        if parsed.get("direction") not in ("long", "short", "wait"):
            logger.warning(f"{key}: invalid direction {parsed.get('direction')}")
            return None
        return {
            "key": key,
            "model": model,
            "name": name,
            "direction": parsed["direction"],
            "confidence": float(parsed.get("confidence", 0.5)),
            "reasoning": parsed.get("reasoning", ""),
        }
    except (json.JSONDecodeError, KeyError):
        pass

    import re
    m = re.search(r'"direction"\s*:\s*"(long|short|wait)"', content)
    if m:
        direction = m.group(1)
        m2 = re.search(r'"confidence"\s*:\s*([\d.]+)', content)
        confidence = float(m2.group(1)) if m2 else 0.5
        m3 = re.search(r'"reasoning"\s*:\s*"(.+?)"(?:\s*[,}])', content, re.DOTALL)
        reasoning = m3.group(1)[:200] if m3 else ""
        logger.warning(f"{key}: JSON parse failed, extracted direction={direction}")
        return {
            "key": key,
            "model": model,
            "name": name,
            "direction": direction,
            "confidence": confidence,
            "reasoning": reasoning,
        }

    logger.warning(f"{key}: failed to parse response")
    return None
