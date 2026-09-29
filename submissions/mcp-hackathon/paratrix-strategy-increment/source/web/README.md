# Research workbench

The workbench uses plain HTML, CSS, and JavaScript served from the application's origin. It needs no separate frontend build or third-party CDN. The Worker serves files through its static-assets binding in both local development and the hosted deployment.

- `/` returns `index.html`; `/static/styles.css` and `/static/app.js` provide the stylesheet and application script.
- Examples, input validation, three-scenario calculations, immutable experiments, and evidence packages all use the `/v1/` API. The browser formats and plots API values without a second financial calculation engine.
- The workflow includes public examples, two JSON imports, an explicit interval, facts-only mode or all four criteria, experiments derived from history, equity/drawdown paths, provenance, and evidence downloads. External Nexus connections are not supported by this application.
- The interface may use Chinese. API errors and backend diagnostic text are English; browser presentation localizes values without changing saved calculations or evidence.
- Dynamic text uses DOM `textContent`. There is no `innerHTML`, inline script, inline event handler, external font, or telemetry request.
- Dates use the API's UTC valuation boundaries. Save times are displayed in Beijing time. Chart rounding is for display only; outcomes come directly from the backend.
- JSON uploads send original file text for strict server-side parsing and use the returned normalized snapshot. They do not rewrite input precision through browser floating-point parsing and serialization. Facts-only mode also displays all four backend-calculated differences.

Records are stored on the server and accessed through a browser cookie that lasts 30 days. Clearing or expiring that cookie prevents access to the former session's private experiments; it does not delete the stored records. Download evidence packages for long-term retention.
