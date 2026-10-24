// P3-BE-09: 200 concurrent SSE clients held open for 40 s (k6 has no EventSource; an open GET is the load).
// Watch `sse_clients` on /metrics while it runs. Expect the requests to end by timeout, not by error.
// The API caps SSE at 10 per IP, so each VU sends its own X-Forwarded-For (the API trusts the UI proxy's).
// Run: docker run --rm -i -e BASE_URL=http://host.docker.internal:8000 grafana/k6:1.3.0 run - < docs/perf/k6/sse.js
import http from "k6/http";

const BASE = `${__ENV.BASE_URL || "http://localhost:8000"}/api/v1`;

export const options = {
  scenarios: { sse: { executor: "per-vu-iterations", vus: 200, iterations: 1, maxDuration: "90s" } },
  thresholds: { "http_req_failed": ["rate<1"] },
};

export default function () {
  const ip = `10.9.${Math.floor(__VU / 250)}.${__VU % 250}`;
  http.get(`${BASE}/stream`, {
    headers: { Accept: "text/event-stream", "X-Forwarded-For": ip },
    timeout: "40s",
    tags: { name: "stream" },
  });
}
