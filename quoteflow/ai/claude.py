"""Claude adapter (Anthropic Messages API over HTTPS).

Security notes: no `tools` are passed, so the model cannot call anything; the reply is plain text that we parse as
JSON and then validate against a strict schema. The catalogue sent to the model contains NO prices."""
import json
import re
import requests
from .prompts import SYSTEM_PROMPT, build_user_prompt

API_URL = "https://api.anthropic.com/v1/messages"


class ProviderError(Exception):
    pass


def parse_json_object(text: str) -> dict:
    """Pull the first balanced JSON object out of the model reply (tolerates code fences / chatter)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        v = json.loads(text)
        if isinstance(v, dict):
            return v
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        v = json.loads(text[start:i + 1])
                        if isinstance(v, dict):
                            return v
                    except json.JSONDecodeError:
                        break
                    break
        start = text.find("{", start + 1)
    raise ProviderError("Model reply did not contain a valid JSON object")


class ClaudeProvider:
    name = "claude"

    def __init__(self, api_key: str, model: str, http=None, timeout=40):
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        self.api_key, self.model, self.timeout = api_key, model, timeout
        self.http = http or requests

    def extract(self, text: str, catalogue: list, today_iso: str, hint: str = "") -> dict:
        user = build_user_prompt(text, catalogue, today_iso)
        if hint:
            user += f"\n\nYour previous reply was rejected: {hint}\nReturn corrected JSON only."
        body = {"model": self.model, "max_tokens": 1800, "temperature": 0,
                "system": SYSTEM_PROMPT, "messages": [{"role": "user", "content": user}]}
        try:
            r = self.http.post(API_URL, json=body, timeout=self.timeout, headers={
                "x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        except requests.RequestException as e:
            raise ProviderError(f"Could not reach the AI service: {type(e).__name__}")
        if r.status_code != 200:
            raise ProviderError(f"AI service returned HTTP {r.status_code}")
        try:
            blocks = r.json().get("content", [])
            reply = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (ValueError, AttributeError):
            raise ProviderError("Unreadable AI service response")
        return parse_json_object(reply)


class OfflineProvider:
    name = "offline"

    def extract(self, text, catalogue, today_iso, hint=""):
        from datetime import date
        from .offline import extract
        return extract(text, catalogue, date.fromisoformat(today_iso))
