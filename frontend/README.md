# Millennium Corpus frontend

The web app has two parts:

- **`ui/`** is the user interface: a React (TanStack Start) app in the [dragon-tattoo-oracle](https://github.com/kubilaycaglayan/dragon-tattoo-oracle) repository, included here as a git submodule. That repository is connected to Lovable, so commits pushed to its `main` show up in the Lovable editor. Lovable's preview answers with built-in sample answers; it never reaches the pipeline.
- **`server.js`** is a small Express server. It serves the built UI, asks the existing `/ask` pipeline, keeps Langfuse credentials off the browser, and sends user ratings to Langfuse. Answers and question history stay in the browser.

Requires Node 22. Fetch the UI with `git submodule update --init` (or clone this repository with `--recurse-submodules`). The UI repository is private, so git needs GitHub credentials for it; `gh auth setup-git` configures them when the GitHub CLI is signed in.

Copy `example.env` to `.env`, fill in the Langfuse project keys, and make sure the existing API, Qdrant, Ollama, Langfuse, and corpus index are running. Install both parts with `npm install && npm --prefix ui ci`, then start development with `npm run dev` from this directory. The Express server listens on `http://127.0.0.1:43179` and starts the UI's Vite dev server on `http://127.0.0.1:43180` (`UI_DEV_PORT`), which reloads on change and sends `/api` requests to Express; open the second address. For a built UI, run `npm run build && npm start` and open `http://127.0.0.1:43179`. `npm test` runs the server tests and the UI tests.

The build sets `STATIC_SPA=true`, which turns the UI into a static single-page app in `ui/dist/client`; the Express server serves those files and every `/api` route. Without it, the UI builds for Lovable's own hosting.

To update the UI, commit inside `ui/`, push it to the UI repository, then commit the new submodule pointer here (`git add frontend/ui`).

The server reads `frontend/.env` when present. `RAG_API_URL` is the server-side API address; `LANGFUSE_BASE_URL` is the server-side Langfuse address; `LANGFUSE_UI_URL` is the browser-reachable Langfuse address.

For Docker, check out the submodule, then run `docker compose up -d --build --no-deps frontend` from the repository root after the API is running. The image builds the UI from `ui/` and serves it with the Express server. The frontend service uses host networking and listens on `127.0.0.1:43179`. It reads the existing root `.env` for Langfuse keys and connects to the existing API on port `8001`.

To publish the frontend through a dashboard-managed Cloudflare Tunnel, set `CLOUDFLARE_PRODUCTION_TUNNEL_TOKEN` in the root `.env` and run `docker compose --profile cloudflare up -d --build --no-deps frontend cloudflared` after the API is running. In Cloudflare, configure a published application route for your chosen hostname with service URL `http://127.0.0.1:43179`. The tunnel connector and frontend share the host network; the frontend stays bound to loopback. The tunnel UUID is not needed to run this connector.

Interactive questions and feedback use the Langfuse `interactive-ui` environment. The Python `/ask` endpoint supplies exact trace and pipeline IDs. The frontend server listens on `FRONTEND_PORT` (default `43179`).

Interactive question traces store the client's IP address as `clientIp` metadata on the root “rag ask” observation. With `TRUST_CLOUDFLARE_PROXY=true`, the frontend uses `CF-Connecting-IP` only when the connection comes from loopback. Other forwarding headers are ignored. Keep the frontend bound to loopback when enabling this setting.

In production (`NODE_ENV=production`), the frontend allows one active `/api/ask` request per remote client IP and returns HTTP 429 for another request until the first finishes. Loopback clients (`127.0.0.0/8` and `::1`) are exempt, including when the local Docker image has `NODE_ENV=production`. This limit is held in the frontend process; deployments with multiple frontend instances need a shared limiter. The Docker Compose app API listens on loopback so remote clients cannot bypass the frontend limit by calling `/ask` directly. The Compose frontend enables trusted Cloudflare client IP handling and secure session cookies for its local tunnel origin.

The production app also enforces rolling per-IP quotas for remote frontend questions: 3 per minute, 10 per 30 minutes, 15 per hour, and 25 per day. An accepted question consumes one quota entry even if its answer later fails; rejected or invalid requests do not. Quotas are stored in `EXPERIMENT_DATA_DIR/frontend-rate-limits.sqlite3`, so they survive service restarts. A quota rejection returns HTTP 429 with `Retry-After`. Set `FRONTEND_RATE_LIMIT_ENABLED=true` on the app to enable these quotas; the Docker Compose app sets it already. The frontend marks requests as production only when `NODE_ENV=production`. Loopback, development, and direct API requests are exempt.

“View trace” opens a panel in the app with the question's Langfuse observation timeline. Trace details are available only to the browser session that asked the question, so the Langfuse UI does not need to be reachable from the browser.
