FROM node:20-trixie-slim AS deps
ARG NPM_VERSION=10.9.4
RUN npm install -g npm@${NPM_VERSION}

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-trixie-slim AS builder
ARG NPM_VERSION=10.9.4
RUN npm install -g npm@${NPM_VERSION}

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_AGENT_URL=http://localhost:8000
ENV NEXT_PUBLIC_AGENT_URL=$NEXT_PUBLIC_AGENT_URL

RUN npm run build

FROM node:20-trixie-slim AS runner
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

WORKDIR /app

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

USER node

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "server.js"]
