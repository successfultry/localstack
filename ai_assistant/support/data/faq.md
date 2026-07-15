# LocalStack Support FAQ

## SignatureDoesNotMatch

Most common causes:

- request is signed for real AWS endpoint but sent to LocalStack endpoint
- region used in signature does not match SDK/client region
- stale or mixed credentials across environment variables and shared config
- service endpoint URL was not explicitly set to LocalStack

Quick checks:

1. Ensure SDK `endpoint_url` points to LocalStack (`http://localhost:4566` by default).
2. Keep one AWS region consistently in SDK config and environment.
3. Verify `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` are set and not mixed with old values.
4. Retry with a minimal reproducible request and debug logs enabled.

## Docker Desktop / container not starting

Typical causes:

- Docker Desktop is stopped or unhealthy
- WSL2 backend is unavailable (Windows)
- container is restart-looping due to low disk or invalid mounted path

Quick checks:

1. `docker ps` and `docker logs localstack-main`.
2. Restart Docker Desktop and rerun container.
3. Validate mounted volumes and available disk.
4. Confirm no port conflicts for LocalStack ports.

## Endpoint URL and region mismatch

Symptoms include redirects, auth errors, and resources "missing" between calls.

Quick checks:

1. Explicitly set LocalStack endpoint in every client in your app.
2. Use one region for all calls in the session.
3. Avoid mixing hostnames (`localhost`, `127.0.0.1`, custom domains) unless configured.

## Pro feature / license troubleshooting

If Pro features are unavailable:

1. Confirm plan is Pro/Team in account settings.
2. Verify auth token is present in runtime environment.
3. Ensure token is provided to the exact process/container running LocalStack.
4. Re-login or refresh token and restart container/process.

## S3 common local endpoint issues

1. Prefer `http://localhost:4566` for S3 endpoint in local runs.
2. Match path-style or virtual-host style with your SDK configuration.
3. Keep bucket region and client region consistent.
4. Validate that requests are not sent to real AWS by proxy or profile settings.

