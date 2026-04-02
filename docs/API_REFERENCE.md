# API Reference

This document details the Request and Response formats for each currently exposed endpoint in the Strat Trade backend. All APIs accept and return JSON payloads unless specified otherwise.

> **Base URL:** The default local host is `http://127.0.0.1:8000`. You can test these endpoints natively through the interactive Swagger UI at `/docs`.

## Standard Error Response
Whenever an error is generated within the domain logic or due to invalid payloads, the API returns an HTTP code (e.g. `400 Bad Request`, `422 Unprocessable Entity`) along with an `ErrorEnvelope`:

```json
{
  "error": {
    "code": "invalid_parameter",
    "message": "Human-readable explanation of what went wrong.",
    "details": {}
  }
}
```

---

## 1. System Health
### `GET /health`
A simple liveness probe to verify the API server is up and responding.

**Request**
- No parameters.

**Response**
```json
{
  "status": "ok"
}
```

---

## 2. Account Balance
### `GET /api/v1/balance`
Returns the current balance for the configured Pocket Option session.

**Request**
- No parameters.

**Response (`BalanceResponse`)**
```json
{
  "amount": 150.50,
  "currency": "USD",
  "is_demo": true
}
```

---

## 3. Market Candles (Tail History)
### `GET /api/v1/market/candles`
Fetches the latest continuous candles (bars) from the broker, sorted ascendingly by open time. Used to fetch "current" state and paginate backward into history.

**Request (Query Parameters)**
- `asset` *(string)*: Pocket Option asset identifier (Default: `EURUSD_otc`).
- `timeframe_seconds` *(int)*: Size of one bar in seconds. Must be native: 1, 5, 15, 30, 60, 300 (Default: `60`).
- `count` *(int)*: Page size or maximum bars to retrieve per request (Default: `100`).
- `end_at` *(datetime, optional)*: ISO 8601 UTC timestamp to anchor the request. Omit it to fetch starting from "now".
- `cursor` *(datetime, optional)*: Pass the `next_cursor` value returned from the previous request to retrieve the preceding batch of historical candles.

**Response (`CandlesResponse`)**
```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "candles": [
    {
      "open_time": "2026-03-22T04:00:00Z",
      "open": 1.1005,
      "high": 1.1010,
      "low": 1.0995,
      "close": 1.1008,
      "volume": 0.0
    }
  ],
  "has_more": true,
  "next_cursor": "2026-03-22T04:00:00Z",
  "total": null,
  "broker_chunk_oldest": null,
  "broker_chunk_newest": null,
  "broker_overlap": null
}
```

---

## 4. Market Candles (Fixed Range)
### `GET /api/v1/market/candles/range`
Fetches historical candles exclusively within a bounded `[from, to]` time window. Designed for fetching sets of data efficiently in one go for backtesting or chart reviews.

**Request (Query Parameters)**
- `asset` *(string)*: Identifier (Default: `EURUSD_otc`).
- `timeframe_seconds` *(int)*: Frequency of candles (Default: `60`).
- `from` *(datetime)*: ISO 8601 UTC timestamp for the start of the interval (inclusive).
- `to` *(datetime)*: ISO 8601 UTC timestamp for the end of the interval (inclusive). Must not be in the future.

**Response (`CandlesResponse`)**
```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "candles": [
    {
      "open_time": "2026-03-22T04:00:00Z",
      "open": 1.1005,
      "high": 1.1010,
      "low": 1.0995,
      "close": 1.1008,
      "volume": 0.0
    }
  ],
  "has_more": false,
  "next_cursor": null,
  "total": 30,
  "broker_chunk_oldest": "2026-03-22T01:00:00Z",
  "broker_chunk_newest": "2026-03-22T05:00:00Z",
  "broker_overlap": true
}
```
