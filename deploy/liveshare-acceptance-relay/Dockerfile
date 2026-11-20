# Mobile Harness LiveShare acceptance Relay
# Build context is the repository root:
#   docker build -f deploy/liveshare-acceptance-relay/Dockerfile .
FROM node:22-alpine

WORKDIR /app
RUN npm init -y >/dev/null 2>&1 \
 && npm install ws@8.18.0 --no-audit --no-fund

COPY tests/smoke/fixtures/liveshare-relay.cjs /app/relay.cjs

ENV MH_RELAY_HOST=0.0.0.0 \
    MH_RELAY_PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:8080/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "/app/relay.cjs", "/app/node_modules/ws"]
