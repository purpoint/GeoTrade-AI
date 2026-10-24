// P3-BE-09: cached and uncached read endpoints. Targets from HLD 8.4 (plan G3):
//   cached p95 < 100 ms, uncached stock summary p95 < 400 ms.
// Run: docker run --rm -i -e BASE_URL=http://host.docker.internal:8000 grafana/k6:1.3.0 run - < docs/perf/k6/api.js
import http from "k6/http";
import { check } from "k6";

const BASE = `${__ENV.BASE_URL || "http://localhost:8000"}/api/v1`;
const TICKERS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "ITC", "LT", "ADANIENT", "WIPRO"];

export const options = {
  scenarios: {
    cached: { executor: "constant-vus", vus: 20, duration: "45s", exec: "cached" },
    uncached: { executor: "constant-arrival-rate", rate: 20, timeUnit: "1s", duration: "45s", preAllocatedVUs: 20, exec: "uncached" },
  },
  thresholds: {
    "http_req_duration{scenario:cached}": ["p(95)<100"],
    "http_req_duration{scenario:uncached}": ["p(95)<400"],
    http_req_failed: ["rate<0.01"],
  },
};

// The API allows 300 requests a minute per IP, so each VU and iteration sends its own forwarded address
// (the API trusts X-Forwarded-For from the UI proxy). Without this the run measures the rate limiter.
const as = () => ({ headers: { "X-Forwarded-For": `10.${__VU % 250}.${Math.floor(__ITER / 250) % 250}.${__ITER % 250}` } });

export function cached() {
  const r = http.get(`${BASE}/market/overview`, { ...as(), tags: { name: "overview" } });
  check(r, { "200": (x) => x.status === 200 });
  http.get(`${BASE}/sectors`, { ...as(), tags: { name: "sectors" } });
}

// a unique query string defeats the 20 s response cache, so every request does the real work
export function uncached() {
  const t = TICKERS[__ITER % TICKERS.length];
  const r = http.get(`${BASE}/stocks/${t}?nocache=${__VU}-${__ITER}`, { ...as(), tags: { name: "stock" } });
  check(r, { "200": (x) => x.status === 200 });
}
