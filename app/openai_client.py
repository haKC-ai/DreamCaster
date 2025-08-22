# app/openai_client.py
import base64
import json
import logging
import re
from typing import Any, Dict, Optional, Iterable

from openai import OpenAI

logger = logging.getLogger("dreamcaster")

_B64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


def _looks_like_b64(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    if len(s) < 100:
        return False
    return bool(_B64_RE.match(s))


def _decode_b64(s: Optional[str]) -> Optional[bytes]:
    if not s:
        return None
    try:
        return base64.b64decode(s, validate=False)
    except Exception as e:
        logger.warning("Base64 decode failed: %s", e)
        return None


def _to_dict(obj: Any) -> Optional[Dict[str, Any]]:
    try:
        return obj.model_dump()  
    except Exception:
        pass
    try:
        d = obj.__dict__
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    try:
        j = obj.json()  
        return json.loads(j)
    except Exception:
        pass
    return None


def _walk(obj: Any) -> Iterable[Any]:
    if obj is None:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield v
            yield from _walk(v)
        return
    if isinstance(obj, (list, tuple)):
        for it in obj:
            yield it
            yield from _walk(it)
        return
    d = _to_dict(obj)
    if d is not None:
        yield d
        yield from _walk(d)


def _find_b64_anywhere(obj: Any) -> Optional[str]:
    preferred_keys = {
        "image_base64",
        "b64_json",
        "base64",
        "data",          
        "image",        
        "content",      
    }
    stack = list(_walk(obj)) if not isinstance(obj, dict) else [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k in preferred_keys:
                if k in cur:
                    v = cur[k]
                    if isinstance(v, str) and _looks_like_b64(v):
                        return v
                    if isinstance(v, dict):
                        for kk, vv in v.items():
                            if isinstance(vv, str) and _looks_like_b64(vv):
                                return vv
            for v in cur.values():
                if isinstance(v, str) and _looks_like_b64(v):
                    return v
                d = _to_dict(v)
                if d is not None:
                    stack.append(d)
                elif isinstance(v, (list, tuple, dict)):
                    stack.append(v)
        elif isinstance(cur, (list, tuple)):
            for it in cur:
                if isinstance(it, str) and _looks_like_b64(it):
                    return it
                d = _to_dict(it)
                if d is not None:
                    stack.append(d)
                elif isinstance(it, (list, tuple, dict)):
                    stack.append(it)
        else:
            d = _to_dict(cur)
            if d is not None:
                stack.append(d)
    return None


def generate_image(
    prompt: str,
    api_key: str,
    model: str = "gpt-4o",
    size: str = "1024x1024",
    output_format: str = "png",
    background: str = "auto",
    timeout: int = 120,
) -> Optional[bytes]:

    client = OpenAI(api_key=api_key, timeout=timeout)

    try:
        resp = client.responses.create(
            model=model,
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            tools=[{
                "type": "image_generation",
                "size": size,              
                "quality": "high",
                "background": background,  # "transparent" or "auto"
                "output_format": output_format,  
            }],
            tool_choice={"type": "image_generation"},
            temperature=1,
            max_output_tokens=2048,
            top_p=1,
            store=False,
        )
        b64 = _find_b64_anywhere(resp)
        img = _decode_b64(b64)
        if img:
            return img
        logger.error("No base64 image found in Responses payload. Falling back to Images API.")
    except Exception as e:
        logger.error("OpenAI generation error")
        logger.exception(e)

    # Fallback
    try:
        img_model = "gpt-image-1"
        img = client.images.generate(
            model=img_model,
            prompt=prompt,
            size=size,
            response_format="b64_json",
        )
        b64 = None
        if hasattr(img, "data") and img.data:
            b64 = getattr(img.data[0], "b64_json", None)
        if not b64:
            d = _to_dict(img) or {}
            b64 = _find_b64_anywhere(d)
        return _decode_b64(b64)
    except Exception as e:
        logger.exception("Images API fallback failed: %s", e)
        return None
