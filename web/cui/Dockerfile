# cui Web UI Dockerfile — Node.js service
FROM node:20-slim

# Install build tools for native modules (better-sqlite3)
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 make g++ && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy all source first (postinstall.js needed during npm ci)
COPY . .

# Install dependencies
RUN npm ci --omit=dev

# Build
RUN npm run build

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD node -e "fetch('http://localhost:3001/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))" || exit 1

CMD ["npm", "start"]
