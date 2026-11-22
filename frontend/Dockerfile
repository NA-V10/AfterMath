# AFTERMATH web app. SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE.
#   docker build -f frontend/Dockerfile --build-arg NEXT_PUBLIC_API_ORIGIN=http://localhost:8000 -t aftermath-web .

FROM node:24.11-bookworm-slim AS build
RUN npm install -g pnpm@12.3.4
WORKDIR /srv/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend ./
# The browser calls the API directly, so its public origin is fixed at build time.
ARG NEXT_PUBLIC_API_ORIGIN=http://localhost:8000
ENV NEXT_PUBLIC_API_ORIGIN=$NEXT_PUBLIC_API_ORIGIN NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:24.11-bookworm-slim
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /srv
COPY --from=build --chown=node:node /srv/frontend/.next/standalone ./
COPY --from=build --chown=node:node /srv/frontend/.next/static ./.next/static
COPY --from=build --chown=node:node /srv/frontend/public ./public
USER node
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
  CMD node -e "fetch('http://127.0.0.1:3000/command').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
