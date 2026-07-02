FROM node:20-trixie-slim AS deps
RUN npm install -g npm@latest

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-trixie-slim AS builder
RUN npm install -g npm@latest

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_AGENT_URL=http://localhost:8000
ENV NEXT_PUBLIC_AGENT_URL=$NEXT_PUBLIC_AGENT_URL

RUN npm run build

FROM node:20-trixie-slim AS runner
RUN npm install -g npm@latest \
    && apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/next.config.mjs ./next.config.mjs

USER node

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["npm", "start"]