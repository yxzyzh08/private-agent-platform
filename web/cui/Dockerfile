# cui Web UI Dockerfile — Node.js service
FROM node:22-slim

# Install build tools for native modules (better-sqlite3) + git for Claude CLI
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 make g++ git openssh-client && \
    rm -rf /var/lib/apt/lists/*

# Install Claude CLI globally
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

# Copy all source first (postinstall.js needed during npm ci)
COPY . .

# Install ALL dependencies (dev deps needed for build: vite, tsc, etc.)
# --ignore-scripts skips husky prepare hook, then manually run postinstall and rebuild native modules
RUN npm ci --ignore-scripts && \
    node scripts/postinstall.js && \
    npm rebuild better-sqlite3

# Build (requires vite, tsc from devDependencies)
RUN npm run build

# Remove dev dependencies after build
RUN npm prune --omit=dev

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD node -e "fetch('http://localhost:3001/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))" || exit 1

CMD ["node", "dist/server.js", "--host", "0.0.0.0"]
