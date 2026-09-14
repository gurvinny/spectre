# SPECTRE web image (Next.js standalone)
# Author: gurvinny
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

FROM node:20-slim AS builder
WORKDIR /app
# NEXT_PUBLIC_API_BASE is inlined into the client bundle at build time.
ARG NEXT_PUBLIC_API_BASE=http://localhost:8100
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
RUN useradd --uid 10001 --create-home spectre
COPY --from=builder /app/public ./public
COPY --from=builder --chown=spectre:spectre /app/.next/standalone ./
COPY --from=builder --chown=spectre:spectre /app/.next/static ./.next/static
USER spectre
EXPOSE 3000
# Lets the orchestrator see a wedged Next server rather than a running process.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD node -e "require('http').get('http://127.0.0.1:3000/',r=>process.exit(r.statusCode<500?0:1)).on('error',()=>process.exit(1))"
CMD ["node", "server.js"]
