"""
Pocket Option / Engine.IO handshake quirks.

pocketoptionapi_async may receive a valid second WebSocket frame that does not match
``startswith("40") and "sid" in msg``. In that case the stock client logs a warning and
*never sends* the auth line, so authentication always times out and connect() returns false.
"""

from __future__ import annotations

import asyncio
import logging
import types

from pocketoptionapi_async.exceptions import WebSocketError

logger = logging.getLogger(__name__)


def _decode_ws_payload(message: object) -> str:
    if isinstance(message, memoryview):
        return bytes(message).decode("utf-8")
    if isinstance(message, (bytes, bytearray)):
        return message.decode("utf-8")
    return str(message)


async def _resilient_send_handshake(self: object, ssid: str) -> None:
    if not self.websocket:
        raise WebSocketError("WebSocket is not connected during handshake")
    try:
        initial_raw = await asyncio.wait_for(self.websocket.recv(), timeout=10.0)
        initial_s = _decode_ws_payload(initial_raw)
        logger.debug("PO WS handshake initial: %s", initial_s[:200])

        if initial_s.startswith("0") and "sid" in initial_s:
            await self.send_message("40")
            conn_raw = await asyncio.wait_for(self.websocket.recv(), timeout=10.0)
            conn_s = _decode_ws_payload(conn_raw)
            logger.debug("PO WS handshake after 40: %s", conn_s[:200])
            if conn_s.startswith("40") and "sid" in conn_s:
                await self.send_message(ssid)
            else:
                logger.warning(
                    "PO WS: second frame not in strict 40+sid shape; sending auth anyway (%r…)",
                    conn_s[:100],
                )
                await self.send_message(ssid)
        else:
            logger.warning(
                "PO WS: first frame not 0+sid; sending 40 then auth anyway (%r…)",
                initial_s[:100],
            )
            await self.send_message("40")
            conn_raw = await asyncio.wait_for(self.websocket.recv(), timeout=10.0)
            conn_s = _decode_ws_payload(conn_raw)
            logger.debug("PO WS handshake recovery after 40: %s", conn_s[:200])
            await self.send_message(ssid)

        logger.debug("PO WS handshake finished (auth sent)")
    except TimeoutError as exc:
        logger.error("PO WS handshake timeout")
        raise WebSocketError("Handshake timeout") from exc


def attach_resilient_handshake(ws: object) -> None:
    ws._send_handshake = types.MethodType(_resilient_send_handshake, ws)  # type: ignore[method-assign]
