# Millennium Corpus frontend

This Vue app asks the existing `/ask` pipeline. The Node server serves the UI, keeps Langfuse credentials off the browser, and sends user ratings to Langfuse. Answers and question history stay in this browser.

Requires Node 22. Copy `example.env` to `.env`, fill in the Langfuse project keys, and make sure the existing API, Qdrant, Ollama, Langfuse, and corpus index are running. Start the development UI with `npm install && npm run dev` from this directory. The default address is `http://127.0.0.1:43179`. For a built UI, run `npm run build && npm start`.

The server reads `frontend/.env` when present. `RAG_API_URL` is the server-side API address; `LANGFUSE_BASE_URL` is the server-side Langfuse address; `LANGFUSE_UI_URL` is the browser-reachable Langfuse address.

For Docker, run `docker compose up -d --build --no-deps frontend` from the repository root after the API is running. The frontend service uses host networking and listens on port `43179`. It reads the existing root `.env` for Langfuse keys and connects to the existing API on port `8001`.

Interactive questions and feedback use the Langfuse `interactive-ui` environment. The Python `/ask` endpoint supplies exact trace and pipeline IDs. The frontend server listens on `FRONTEND_PORT` (default `43179`).

Interactive question traces store the connecting client's IP address as `clientIp` metadata on the root “rag ask” observation. The frontend uses the direct connection address; if deployed behind a reverse proxy, this will be the proxy's IP address. Browser-supplied forwarding headers are ignored.

In production (`NODE_ENV=production`), the frontend allows one active `/api/ask` request per connection IP and returns HTTP 429 for another request until the first finishes. This limit is held in the frontend process; deployments with multiple frontend instances need a shared limiter. The Docker Compose app API listens on loopback so remote clients cannot bypass the frontend limit by calling `/ask` directly.

“View trace” opens a panel in the app with the question's Langfuse observation timeline. Trace details are available only to the browser session that asked the question, so the Langfuse UI does not need to be reachable from the browser.
