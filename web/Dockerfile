ARG NODE_BASE_IMAGE=docker.m.daocloud.io/library/node:22-slim
ARG NPM_REGISTRY=https://registry.npmmirror.com/

FROM ${NODE_BASE_IMAGE} AS deps
ARG NPM_REGISTRY
WORKDIR /app

COPY package.json package-lock.json ./
COPY web/package.json ./web/
COPY web/scripts ./web/scripts
ENV PUPPETEER_SKIP_DOWNLOAD=true
RUN npm config set registry ${NPM_REGISTRY} && \
    npm install --legacy-peer-deps --no-audit --no-fund

FROM ${NODE_BASE_IMAGE} AS builder
WORKDIR /app

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_APP_BASE_PATH=
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_APP_BASE_PATH=${NEXT_PUBLIC_APP_BASE_PATH}

COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/web/node_modules ./web/node_modules
COPY package.json package-lock.json ./
COPY web ./web
RUN NODE_OPTIONS="--max-old-space-size=4096" npm run build:web

FROM ${NODE_BASE_IMAGE} AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ARG NEXT_PUBLIC_APP_BASE_PATH=
ENV NEXT_PUBLIC_APP_BASE_PATH=${NEXT_PUBLIC_APP_BASE_PATH}

RUN groupadd --system --gid 1001 nodejs && \
    useradd --system --uid 1001 --gid nodejs nextjs

COPY --from=builder /app/web/public ./web/public
COPY --from=builder /app/web/.next/standalone ./
COPY --from=builder /app/web/.next/static ./web/.next/static

USER nextjs

EXPOSE 3000
CMD ["node", "web/server.js"]
