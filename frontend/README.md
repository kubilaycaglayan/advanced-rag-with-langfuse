# Millennium Corpus frontend

This Vue app asks the existing `/ask` pipeline. The Node server serves the UI, keeps Langfuse credentials off the browser, and sends user ratings to Langfuse. Answers and question history stay in this browser.

Requires Node 22. Copy `example.env` to `.env`, fill in the Langfuse project keys, and make sure the existing API, Qdrant, Ollama, Langfuse, and corpus index are running. Start the development UI with `npm install && npm run dev` from this directory. The default address is `http://127.0.0.1:43179`. For a built UI, run `npm run build && npm start`.

The server reads `frontend/.env` when present. `RAG_API_URL` is the server-side API address; `LANGFUSE_BASE_URL` is the server-side Langfuse address; `LANGFUSE_UI_URL` is the browser-reachable Langfuse address.

For Docker, run `docker compose up -d --build --no-deps frontend` from the repository root after the API is running. The frontend service uses host networking and listens on `127.0.0.1:43179`. It reads the existing root `.env` for Langfuse keys and connects to the existing API on port `8001`.

To publish the frontend through a dashboard-managed Cloudflare Tunnel, set `CLOUDFLARE_PRODUCTION_TUNNEL_TOKEN` in the root `.env` and run `docker compose --profile cloudflare up -d --build --no-deps frontend cloudflared` after the API is running. In Cloudflare, configure a published application route for your chosen hostname with service URL `http://127.0.0.1:43179`. The tunnel connector and frontend share the host network; the frontend stays bound to loopback. The tunnel UUID is not needed to run this connector.

Interactive questions and feedback use the Langfuse `interactive-ui` environment. The Python `/ask` endpoint supplies exact trace and pipeline IDs. The frontend server listens on `FRONTEND_PORT` (default `43179`).

Interactive question traces store the client's IP address as `clientIp` metadata on the root “rag ask” observation. With `TRUST_CLOUDFLARE_PROXY=true`, the frontend uses `CF-Connecting-IP` only when the connection comes from loopback. Other forwarding headers are ignored. Keep the frontend bound to loopback when enabling this setting.

In production (`NODE_ENV=production`), the frontend allows one active `/api/ask` request per remote client IP and returns HTTP 429 for another request until the first finishes. Loopback clients (`127.0.0.0/8` and `::1`) are exempt, including when the local Docker image has `NODE_ENV=production`. This limit is held in the frontend process; deployments with multiple frontend instances need a shared limiter. The Docker Compose app API listens on loopback so remote clients cannot bypass the frontend limit by calling `/ask` directly. The Compose frontend enables trusted Cloudflare client IP handling and secure session cookies for its local tunnel origin.

The production app also enforces rolling per-IP quotas for remote frontend questions: 3 per minute, 10 per 30 minutes, 15 per hour, and 25 per day. An accepted question consumes one quota entry even if its answer later fails; rejected or invalid requests do not. Quotas are stored in `EXPERIMENT_DATA_DIR/frontend-rate-limits.sqlite3`, so they survive service restarts. A quota rejection returns HTTP 429 with `Retry-After`. Set `FRONTEND_RATE_LIMIT_ENABLED=true` on the app to enable these quotas; the Docker Compose app sets it already. The frontend marks requests as production only when `NODE_ENV=production`. Loopback, development, and direct API requests are exempt.

“View trace” opens a panel in the app with the question's Langfuse observation timeline. Trace details are available only to the browser session that asked the question, so the Langfuse UI does not need to be reachable from the browser.
