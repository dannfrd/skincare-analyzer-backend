from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Iterable


class JWTError(Exception):
    pass


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _json_dumps(data: dict[str, Any]) -> bytes:
    return json.dumps(data, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")


def _is_iterable_algorithms(algorithms: Any) -> set[str]:
    if algorithms is None:
        return {"HS256"}
    if isinstance(algorithms, str):
        return {algorithms}
    if isinstance(algorithms, Iterable):
        return {str(item) for item in algorithms}
    return {str(algorithms)}


class _JWTModule:
    @staticmethod
    def encode(payload: dict[str, Any], key: str, algorithm: str = "HS256") -> str:
        if algorithm != "HS256":
            raise JWTError(f"Unsupported algorithm: {algorithm}")

        header = {"typ": "JWT", "alg": algorithm}
        header_segment = _base64url_encode(_json_dumps(header))
        payload_segment = _base64url_encode(_json_dumps(payload))
        signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
        signature = hmac.new(key.encode("utf-8"), signing_input, hashlib.sha256).digest()
        signature_segment = _base64url_encode(signature)
        return f"{header_segment}.{payload_segment}.{signature_segment}"

    @staticmethod
    def decode(token: str, key: str, algorithms: list[str] | tuple[str, ...] | set[str] | None = None) -> dict[str, Any]:
        try:
            header_segment, payload_segment, signature_segment = token.split(".")
        except ValueError as exc:
            raise JWTError("Invalid token format") from exc

        try:
            header = json.loads(_base64url_decode(header_segment).decode("utf-8"))
            payload = json.loads(_base64url_decode(payload_segment).decode("utf-8"))
        except Exception as exc:
            raise JWTError("Invalid token payload") from exc

        algorithm = str(header.get("alg", ""))
        allowed_algorithms = _is_iterable_algorithms(algorithms)
        if algorithm not in allowed_algorithms:
            raise JWTError(f"Algorithm {algorithm} is not allowed")

        signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
        expected_signature = hmac.new(key.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual_signature = _base64url_decode(signature_segment)
        if not hmac.compare_digest(expected_signature, actual_signature):
            raise JWTError("Signature verification failed")

        exp = payload.get("exp")
        if exp is not None:
            try:
                exp_value = float(exp)
            except (TypeError, ValueError) as exc:
                raise JWTError("Invalid expiration claim") from exc
            now = datetime.now(timezone.utc).timestamp()
            if now >= exp_value:
                raise JWTError("Token has expired")

        return payload


jwt = _JWTModule()
