"""Coordinator bulletin in English or Hindi.

The deterministic bulletin is always produced from the action card. When an
Amazon Bedrock model is configured, the model may only re-word/translate the
same structured facts. Its output is rejected (and the deterministic text is
used) if it introduces any number or clock time not present in the facts, is
too long, or the call fails. The model never computes AQI, picks thresholds,
infers causes, gives medical advice or changes the plan.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .guidance import INDOOR_NOTE, SOURCE

CAT_HI = {
    "good": "अच्छा", "moderate": "मध्यम", "usg": "संवेदनशील समूहों के लिए अस्वास्थ्यकर", "unhealthy": "अस्वास्थ्यकर",
    "very_unhealthy": "बहुत अस्वास्थ्यकर", "hazardous": "खतरनाक", "beyond": "AQI पैमाने से ऊपर", "unavailable": "उपलब्ध नहीं",
}
GUIDE_HI = {
    "good": "बाहर सक्रिय रहने के लिए बहुत अच्छा दिन।",
    "moderate": "बाहर सक्रिय रहने के लिए अच्छा दिन। वायु प्रदूषण के प्रति असामान्य रूप से संवेदनशील छात्रों में लक्षण हो सकते हैं।",
    "usg": "बाहर सक्रिय रहना ठीक है, विशेषकर रिसेस और PE जैसी छोटी गतिविधियों के लिए। लंबी गतिविधियों में अधिक विराम लें और कम तीव्र "
           "गतिविधियाँ करें। लक्षणों पर ध्यान दें; अस्थमा वाले छात्र अपनी अस्थमा कार्य योजना का पालन करें।",
    "unhealthy": "सभी बाहरी गतिविधियों में अधिक विराम लें और कम तीव्र गतिविधियाँ करें। लंबी या अधिक तीव्र गतिविधियों को भवन के अंदर ले "
                 "जाने या किसी अन्य दिन/समय पर करने पर विचार करें। लक्षणों पर ध्यान दें; अस्थमा वाले छात्र अपनी अस्थमा कार्य योजना का पालन करें।",
    "very_unhealthy": "सभी गतिविधियाँ भवन के अंदर ले जाएँ या उन्हें किसी अन्य दिन के लिए पुनर्निर्धारित करें।",
}
HI_NOTE = "हिंदी पाठ: डेवलपर्स द्वारा तैयार निश्चित टेम्पलेट (AI-सहायता से अनूदित); किसी धाराप्रवाह समीक्षक से जाँच की सलाह दी जाती है।"


def facts_from_card(card: dict) -> dict[str, Any]:
    p = card["planned"]
    alt = card["alternative"] or card["least_polluted"]
    return {
        "organisation": card["org"]["name"], "activity": card["activity"]["name"], "date": card["date"],
        "planned_time_local": p["label"], "timezone": card["org"]["timezone"],
        "participants_estimate": card["activity"]["participants"],
        "aqi_standard": "US AQI", "planned_peak_us_aqi": p["peak_aqi"], "planned_category_key": card["planned_category"]["key"],
        "planned_category": card["planned_category"]["label"], "planning_threshold_us_aqi": card["threshold_aqi"],
        "status": card["status"],
        "alternative": None if not alt else {
            "time_local": alt["label"], "peak_us_aqi": alt["peak_aqi"], "meets_threshold": alt["meets_threshold"],
            "pct_change_vs_planned": (card.get("comparison") or {}).get("pct_change")},
        "data": {"source": "Open-Meteo Air Quality API, CAMS Global model forecast", "resolution": "about 45 km",
                 "retrieved_at": card["provenance"]["retrieved_at"], "data_type": "modelled forecast, not a measurement",
                 "mode": card["provenance"].get("mode")},
        "guidance_en": card["guidance"]["text"], "guidance_source": SOURCE["page_url"],
        "guidance_scope": SOURCE["scope_note"], "indoor_note": INDOOR_NOTE,
    }


def deterministic(f: dict, lang: str) -> str:
    alt = f["alternative"]
    if lang == "hi":
        cat = CAT_HI.get(f["planned_category_key"], f["planned_category"])
        if f["status"] == "within_threshold":
            a = "नियोजित समय आपकी योजना सीमा के भीतर है।"
        elif alt and alt["meets_threshold"]:
            pct = f", PM2.5 सूचकांक में {alt['pct_change_vs_planned']:+.1f}% परिवर्तन" if alt["pct_change_vs_planned"] is not None else ""
            a = f"कम प्रदूषण वाला विकल्प: {alt['time_local']} (अधिकतम US AQI {alt['peak_us_aqi']}{pct})।"
        elif alt:
            a = (f"आपके अनुमत समय में कोई भी समय सीमा के भीतर नहीं है। सबसे कम प्रदूषित समय {alt['time_local']} (अधिकतम US AQI "
                 f"{alt['peak_us_aqi']}) भी सीमा से ऊपर है — यह सुरक्षित समय नहीं है। इनडोर विकल्प, स्थगन या रद्द करने पर विचार करें।")
        else:
            a = "कोई पूर्ण वैकल्पिक समय उपलब्ध नहीं है।"
        lines = [
            f"{f['organisation']} — {f['activity']}, {f['date']}, {f['planned_time_local']} ({f['timezone']})।",
            f"पूर्वानुमानित अधिकतम US AQI: {f['planned_peak_us_aqi']} ({cat})। आपकी योजना सीमा: {f['planning_threshold_us_aqi']}।",
            a,
            f"मार्गदर्शन (AirNow, US EPA — US AQI): {GUIDE_HI.get(_row(f['planned_category_key']), '')}",
            "यह भारत सरकार का निर्देश नहीं है; स्थानीय आधिकारिक प्रतिबंध प्राथमिक हैं।",
            "इनडोर वायु गुणवत्ता सत्यापित नहीं है (कोई इनडोर माप उपलब्ध नहीं)।",
            f"डेटा: Open-Meteo / CAMS Global मॉडल पूर्वानुमान (लगभग 45 किमी), मापन नहीं; प्राप्त: {f['data']['retrieved_at']}।",
        ]
        return "\n".join(lines)
    if f["status"] == "within_threshold":
        a = "The planned time is within your planning threshold."
    elif alt and alt["meets_threshold"]:
        pct = f", {alt['pct_change_vs_planned']:+.1f}% PM2.5 pollution-time index" if alt["pct_change_vs_planned"] is not None else ""
        a = f"Lower-pollution alternative: {alt['time_local']} (peak US AQI {alt['peak_us_aqi']}{pct})."
    elif alt:
        a = (f"No permitted time meets your threshold. The least-polluted permitted time, {alt['time_local']} (peak US AQI "
             f"{alt['peak_us_aqi']}), still exceeds it and is not a safe window. Consider an indoor option, postponing or cancelling.")
    else:
        a = "No complete alternative window is available."
    return "\n".join([
        f"{f['organisation']} — {f['activity']}, {f['date']}, {f['planned_time_local']} ({f['timezone']}).",
        f"Forecast peak US AQI {f['planned_peak_us_aqi']} ({f['planned_category']}); your planning threshold is {f['planning_threshold_us_aqi']}.",
        a,
        f"Guidance (AirNow, US EPA — US AQI): {f['guidance_en']}",
        "This is not an Indian government directive; local official restrictions take precedence.",
        f["indoor_note"],
        f"Data: Open-Meteo / CAMS Global model forecast (about 45 km), not a measurement; retrieved {f['data']['retrieved_at']}.",
    ])


def _row(key: str) -> str:
    return "very_unhealthy" if key in ("hazardous", "beyond") else key


_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_TIME = re.compile(r"\b\d{1,2}:\d{2}\b")


_META = re.compile(r"\s*\((?:word count|words|शब्द(?: संख्या)?)\s*[:：]?\s*\d+\)\s*$", re.IGNORECASE)
_UNITS = re.compile(r"µg|μg|ug/m|mg/m|माइक्रोग्राम", re.IGNORECASE)


def strip_meta(text: str) -> str:
    """Remove a trailing '(Word count: N)' note some models append. Nothing else is altered."""
    return _META.sub("", text or "").strip()


def validate(text: str, f: dict, reference: str) -> str | None:
    """Return a rejection reason, or None if every number/time is grounded in the facts."""
    if not text or len(text) > 1500:
        return "empty or too long"
    if _UNITS.search(text):
        return "mentions concentration units that are not part of the facts"
    norm = text.translate(_DEVANAGARI)
    allowed_src = json.dumps(f, ensure_ascii=False) + "\n" + reference
    allowed_nums = {_canon(n) for n in _NUM.findall(allowed_src)} | {"2.5", "10", "45", "0"}
    allowed_times = set(_TIME.findall(allowed_src))
    for t in _TIME.findall(norm):
        if t not in allowed_times:
            return f"time {t} is not in the facts"
    for n in _NUM.findall(_TIME.sub(" ", norm)):
        if _canon(n) not in allowed_nums:
            return f"number {n} is not in the facts"
    return None


def _canon(n: str) -> str:
    try:
        v = float(n)
    except ValueError:
        return n
    return str(int(v)) if v == int(v) else f"{v:g}"


SYSTEM_PROMPT = (
    "You re-word verified facts into a short bulletin for a school activity coordinator. Use ONLY the facts "
    "given. Do not add numbers, times, causes, health or medical advice, or recommendations not in the facts. "
    "Do not calculate anything. Keep every number and time exactly as given, using Western digits. "
    "Mention that it is a modelled forecast and that the guidance is US AQI guidance from AirNow, not an "
    "Indian government directive. Maximum 120 words. Plain text only. Do not add a word count, title, notes "
    "or any commentary about the text itself."
)
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_NVIDIA_MODEL = "nvidia/nemotron-3-super-120b-a12b"


def _prompt(f: dict, lang: str) -> str:
    language = "Hindi (Devanagari script)" if lang == "hi" else "English"
    return f"Write the bulletin in {language}.\nFACTS (JSON):\n{json.dumps(f, ensure_ascii=False)}"


async def _bedrock(f: dict, lang: str, model_id: str, client: Any | None) -> str:
    if client is None:
        import boto3
        from botocore.config import Config

        client = boto3.client("bedrock-runtime", config=Config(retries={"max_attempts": 2, "mode": "standard"}, read_timeout=20))
    r = client.converse(modelId=model_id, system=[{"text": SYSTEM_PROMPT}],
                        messages=[{"role": "user", "content": [{"text": _prompt(f, lang)}]}],
                        inferenceConfig={"maxTokens": 500, "temperature": 0.2})
    return "".join(c.get("text", "") for c in r["output"]["message"]["content"]).strip()


async def _nvidia(f: dict, lang: str, api_key: str, model: str, http: Any | None) -> str:
    import httpx

    owns = http is None
    http = http or httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=5.0))
    try:
        r = await http.post(NVIDIA_URL, headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"}, json={
            "model": model, "temperature": 0.2, "max_tokens": 600,
            # Reasoning models: disable thinking so the budget goes to the answer.
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": "/no_think\n" + SYSTEM_PROMPT},
                         {"role": "user", "content": _prompt(f, lang)}],
        })
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        return (r.json()["choices"][0]["message"].get("content") or "").strip()
    finally:
        if owns:
            await http.aclose()


async def bulletin(card: dict, lang: str, model_id: str = "", client: Any | None = None,
                   nvidia_key: str = "", nvidia_model: str = DEFAULT_NVIDIA_MODEL, http: Any | None = None) -> dict:
    """Deterministic bulletin always; optional AI wording from Bedrock, else the NVIDIA
    fallback. Any provider output that fails validation is discarded."""
    lang = "hi" if lang == "hi" else "en"
    f = facts_from_card(card)
    det = deterministic(f, lang)
    out: dict[str, Any] = {"lang": lang, "facts": f, "deterministic": det, "ai": None, "ai_attempts": [],
                           "hindi_note": HI_NOTE if lang == "hi" else None}
    providers = []
    if model_id:
        providers.append(("Amazon Bedrock", model_id, lambda: _bedrock(f, lang, model_id, client)))
    if nvidia_key:
        providers.append(("NVIDIA API (fallback)", nvidia_model, lambda: _nvidia(f, lang, nvidia_key, nvidia_model, http)))
    for name, model, call in providers:
        try:
            text = strip_meta(await call())
        except Exception as exc:  # noqa: BLE001 - any failure moves to the next provider
            out["ai_attempts"].append({"provider": name, "model": model, "status": f"failed: {exc.__class__.__name__}"})
            continue
        reason = validate(text, f, det)
        if reason:
            out["ai_attempts"].append({"provider": name, "model": model, "status": f"rejected: {reason}"})
            continue
        out["ai_attempts"].append({"provider": name, "model": model, "status": "accepted"})
        out["ai"] = {"text": text, "provider": name, "model_id": model,
                     "label": f"AI-worded by {name} ({model}). Every number and time was checked against the deterministic "
                              "facts; the plan, AQI values and thresholds are not changed by the model. Only the activity and "
                              "forecast summary shown in 'facts' was sent to the provider (no emails or personal data)."}
        break
    out["ai_status"] = ("accepted" if out["ai"] else
                        "not_configured" if not providers else "fallback_to_deterministic")
    return out
