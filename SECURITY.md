# SkyGrid Enterprise — Security Notes

## Scope

SkyGrid Enterprise is a **research prototype and competition demonstration system**.
It is NOT a production system and is NOT deployed on public infrastructure.

---

## Known Security Considerations

### 1. CORS Configuration
Current setting: `allow_origins=["*"]` (all origins allowed).  
**Risk:** Acceptable for local demo. Must be restricted if exposed to the internet.  
**Fix for production:** Set `allow_origins=["https://your-domain.com"]`.

### 2. No Authentication
The API has no authentication. Any client on the network can call all endpoints.  
**Risk:** Low in a local demo context. Unacceptable for production.  
**Fix for production:** Add API key or OAuth2 token validation.

### 3. Command Endpoint Allowlist
`POST /api/command/{command}` validates the command against an explicit allowlist:
```python
allowed = {
    "scenario_a", "scenario_b", "scenario_c",
    "chaos_pad", "chaos_wind", "chaos_obstacle",
    "reset", "get_state", "get_weather", "fleet_report",
}
```
Commands not in this set return HTTP 400. No shell execution or file access
is performed by any command handler.

### 4. Benchmark Input Validation
`POST /api/benchmark` uses a Pydantic model with `ge`/`le` constraints:
```python
scenarios: int = Field(ge=1, le=50)
orders:    int = Field(ge=1, le=20)
```
Strategy values are validated against the `Strategy` enum before use.

### 5. WebSocket Input
WebSocket messages are parsed as JSON. Invalid JSON returns an error response.
Message content is routed to the command handler which applies the same
allowlist as the REST endpoint.

### 6. No File Upload
No file upload endpoints exist. The benchmark runner writes only to
`results/` (a subdirectory of the project).

### 7. No Database
No SQL database is used. No SQL injection surface exists.

### 8. Dependencies
All dependencies are pinned in `backend/requirements.txt`.
Run `pip audit` or `safety check` before any deployment to verify
no known CVEs in dependencies.

---

## Reporting Issues

This is a competition prototype. Security issues in the context of
the competition evaluation can be reported directly to the project team.
