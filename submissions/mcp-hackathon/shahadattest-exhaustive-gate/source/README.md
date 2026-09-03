# ExhaustiveGate

AI agents often mistake partial retrieval for complete evidence.

ExhaustiveGate verifies whether an agent has actually covered the required result set before allowing claims such as:

- all
- none
- exactly N
- cheapest
- highest
- lowest

**“Finding no more evidence is not the same as proving there is no more evidence.”**

## Quick start

```bash
cd exhaustive-gate/backend
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8100
cd ../examples/demo-crm
python -m uvicorn main:app --port 8101
# open ../frontend/index.html
```

## Docker

```bash
cd exhaustive-gate
docker-compose up --build
# frontend :8102, gate :8100, CRM :8101
```

## Example

```bash
curl -X POST localhost:8100/v1/sessions -H 'Content-Type: application/json' \
  -d '{"resource_type":"invoice","scope":{"status":"unpaid"}}'
```

See `docs/api.md`, `docs/proof-model.md`, `docs/demo.md`. Security: validated inputs,
body caps, no code execution, no upstream fetching in core. License: MIT.
