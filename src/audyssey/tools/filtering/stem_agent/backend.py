"""Audio judge backends: the interface and the OpenAI-compatible chat backend (vLLM, DashScope).

Confidence comes from the first token's logprobs (P(YES) renormalised against P(NO)). If the
server returns no logprobs, it falls back to sampling N answers and using the vote share.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from .audio import Clip
from .config import BackendConfig

# A prompt is an ordered list of parts: plain text or an audio clip.
Part = Union[str, Clip]

YES_WORDS = {"yes", "y"}
NO_WORDS = {"no", "n"}


@dataclass
class YesNo:
    p_yes: Optional[float]  # None = model output could not be parsed
    text: str  # raw text (first line answer + evidence)
    method: str  # "logprobs" | "vote" | "mock" | "parse"

    @property
    def evidence(self) -> str:
        lines = [ln.strip() for ln in self.text.strip().splitlines() if ln.strip()]
        return lines[1] if len(lines) > 1 else (lines[0] if lines else "")


def parse_yes_no(text: str) -> Optional[bool]:
    m = re.search(r"[A-Za-z]+", text or "")
    if not m:
        return None
    w = m.group(0).lower()
    if w in YES_WORDS:
        return True
    if w in NO_WORDS:
        return False
    return None


def p_yes_from_top_logprobs(top: Iterable[Tuple[str, float]]) -> Optional[float]:
    """Renormalise P(YES) vs P(NO) over the first generated token's top candidates."""
    py = pn = 0.0
    for tok, lp in top:
        w = tok.strip().lower()
        if w in YES_WORDS:
            py += math.exp(lp)
        elif w in NO_WORDS:
            pn += math.exp(lp)
    if py + pn <= 0:
        return None
    return py / (py + pn)


class JudgeBackend:
    """Implementations must provide yes_no() and generate()."""

    def yes_no(self, system: str, parts: List[Part], max_tokens: int) -> YesNo:
        raise NotImplementedError

    def generate(self, system: str, parts: List[Part], max_tokens: int) -> str:
        raise NotImplementedError

    def info(self) -> Dict[str, str]:
        return {"backend": type(self).__name__}


class OpenAICompatBackend(JudgeBackend):
    def __init__(self, cfg: BackendConfig):
        self.cfg = cfg
        self.api_key = os.environ.get(cfg.api_key_env, "EMPTY")
        self._logprobs_supported: Optional[bool] = None

    # ------------------------------------------------------------------ request helpers
    def _content(self, parts: List[Part]) -> List[Dict[str, Any]]:
        content: List[Dict[str, Any]] = []
        for p in parts:
            if isinstance(p, Clip):
                if self.cfg.audio_part == "input_audio":
                    content.append(
                        {
                            "type": "input_audio",
                            "input_audio": {"data": p.to_data_uri(), "format": "wav"},
                        }
                    )
                else:
                    content.append(
                        {"type": "audio_url", "audio_url": {"url": p.to_data_uri()}}
                    )
            else:
                content.append({"type": "text", "text": p})
        return content

    def _post(self, body: Dict[str, Any]) -> Dict[str, Any]:
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        data = json.dumps(body).encode("utf-8")
        last_err: Optional[Exception] = None
        for attempt in range(3):
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                    # Cloudflare-fronted proxies (e.g. RunPod) reject the default Python-urllib UA.
                    "User-Agent": "stem-filter-agent/0.1",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                if e.code < 500:
                    raise RuntimeError(
                        f"HTTP {e.code} from judge server: {detail}"
                    ) from e
                last_err = RuntimeError(f"HTTP {e.code}: {detail}")
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
            time.sleep(2**attempt)
        raise RuntimeError(f"judge server unreachable at {url}: {last_err}")

    def _body(
        self, system: str, parts: List[Part], max_tokens: int, **extra: Any
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": [{"type": "text", "text": system}]},
                {"role": "user", "content": self._content(parts)},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }
        body.update(extra)
        return body

    # ------------------------------------------------------------------ public API
    def yes_no(self, system: str, parts: List[Part], max_tokens: int) -> YesNo:
        if self._logprobs_supported is not False:
            resp = self._post(
                self._body(system, parts, max_tokens, logprobs=True, top_logprobs=10)
            )
            choice = resp["choices"][0]
            text = choice["message"].get("content") or ""
            lp = (choice.get("logprobs") or {}).get("content") or []
            if lp:
                self._logprobs_supported = True
                # first token that is not whitespace/punctuation
                for tok in lp:
                    if tok["token"].strip(" \n\t*\"'`:") == "":
                        continue
                    top = [
                        (t["token"].strip(" \n\t*\"'`:"), t["logprob"])
                        for t in tok.get("top_logprobs", [])
                    ]
                    p = p_yes_from_top_logprobs(top)
                    if p is not None:
                        return YesNo(p, text, "logprobs")
                    break
            else:
                self._logprobs_supported = False
            ans = parse_yes_no(text)
            if self.cfg.fallback_samples <= 1:
                return YesNo(None if ans is None else float(ans), text, "parse")
        # sampling vote
        votes, texts = [], []
        for _ in range(max(1, self.cfg.fallback_samples)):
            resp = self._post(
                self._body(
                    system, parts, max_tokens, temperature=self.cfg.fallback_temperature
                )
            )
            t = resp["choices"][0]["message"].get("content") or ""
            texts.append(t)
            a = parse_yes_no(t)
            if a is not None:
                votes.append(a)
        p = (sum(votes) / len(votes)) if votes else None
        return YesNo(p, texts[0] if texts else "", "vote")

    def generate(self, system: str, parts: List[Part], max_tokens: int) -> str:
        resp = self._post(self._body(system, parts, max_tokens))
        return resp["choices"][0]["message"].get("content") or ""

    def info(self) -> Dict[str, str]:
        return {
            "backend": "openai",
            "model": self.cfg.model,
            "base_url": self.cfg.base_url,
        }


def make_backend(cfg: BackendConfig) -> JudgeBackend:
    if cfg.kind == "openai":
        return OpenAICompatBackend(cfg)
    raise ValueError(f"unknown backend kind {cfg.kind!r} (only 'openai' is vendored)")
