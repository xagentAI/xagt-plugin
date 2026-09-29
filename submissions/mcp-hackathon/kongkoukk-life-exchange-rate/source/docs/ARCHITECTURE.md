# Life Exchange Rate MCP — v0.2 architecture

## Product thesis

Every macro headline has a personal exchange rate. The service converts an observed macro event into an auditable estimate of what it means in the user's own budget, work time, and everyday units.

## Flow

`official headlines / market data` → `structured MacroEvent` → `significance + relevance ranking` → `deterministic impact engine` → `MCP tools` → `Agent explanation`

The Agent never owns the core arithmetic.

## Separation of concerns

- **MacroHeadline**: title, publisher, time, URL, jurisdiction, event-type hint. It explicitly requires quantification.
- **MacroEvent**: numeric old/new values, observation window, units, currencies/jurisdiction, evidence, provenance.
- **LifeProfile**: only the exposures needed for the selected scenario.
- **EventScore**: transparent market-significance and user-relevance scores.
- **ImpactResult**: money impact + work/life units + warnings + calculation trace.

## Safety boundary

A Fed rate move is not directly applied to a SEK mortgage. Currency/jurisdiction scope is checked before rate-impact calculation. Cross-border spillovers are outside the MVP.


## Adapters and server lifetime

FX, ECB policy-rate and EIA energy adapters normalize observations into the same `MacroEvent` and support injected HTTP transports for deterministic tests. The service layer owns provider selection. Policy/energy share date validation and fixture handling. Source dates remain separate from retrieval timestamps. FX anomaly statistics exclude the selected event from preceding equal-calendar-horizon reference returns.

FastAPI and MCP share services and models. The mounted MCP application runs its session manager inside the parent lifespan. The SDK manager is single-use; tests share one lifespan per app instance. The canonical endpoint is `/mcp/`. Public deployment hosts are explicitly allowed from `PUBLIC_BASE_URL`.
