# Demo (3-5 min)

1. `docker-compose up --build`, open frontend `http://localhost:3000`, backend `http://localhost:8000/health`.
2. Click **Try Demo API**, enter base URL `http://demo-api:8001` (docker) or `http://localhost:8001` (local).
3. Run analysis: readiness ~60s (issues: undocumented errors, ambiguous `q`, weak schemas).
4. Run live tests: see `GET /weather` return `{"tmp":"31 C","desc":"sun"}` sometimes vs normalized variant.
5. Click **Agentize API**: rules generated (`tmp->temperature_celsius extract_number`, `desc->condition map_enum`, `price extract_number`).
6. Before/after comparison shown (e.g. 62 -> 100 demo, target narrative 43 -> 96).
7. Open generated tool `get_weather`, call proxy with `{}`, show stable `{"temperature_celsius":31,"condition":"sunny",...}`.
8. Download export JSON (tools + rules + report).
