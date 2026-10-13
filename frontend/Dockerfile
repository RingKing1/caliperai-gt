# Sensor Fusion Annotation Platform - Frontend Dockerfile

# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

# Optional HTTP proxy for reaching the npm registry from restricted networks.
# Supplied through docker-compose build args (BUILD_HTTP_PROXY/BUILD_HTTPS_PROXY).
ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY="localhost,127.0.0.1"
ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    no_proxy=${NO_PROXY}

# Copy package files
COPY package.json package-lock.json* yarn.lock* pnpm-lock.yaml* ./

# Install dependencies. Prefer the reproducible `npm ci` when a lockfile is
# present. Some npm versions exit 0 after a registry/network crash, which
# surfaced much later as a misleading "tsc: not found", so verify the install.
RUN set -e; \
    if [ -f pnpm-lock.yaml ]; then \
        corepack enable && pnpm install --frozen-lockfile; \
    elif [ -f yarn.lock ]; then \
        yarn install --frozen-lockfile; \
    elif [ -f package-lock.json ]; then \
        npm ci --no-audit --no-fund; \
    else \
        npm install --no-audit --no-fund; \
    fi; \
    test -x node_modules/.bin/tsc || { \
        echo "ERROR: dependency install incomplete (node_modules/.bin/tsc missing); the npm registry was likely unreachable"; \
        exit 1; \
    }

# Copy source files
COPY . .

# Branding: env/<brand>.env becomes the .env Vite reads when baking VITE_BRAND_* into the bundle.
ARG BRAND=caliper
RUN cp "env/${BRAND}.env" .env

# Build the application
RUN npm run build


# Production stage with nginx
FROM nginx:alpine AS production

# Copy custom nginx config (use proxy config for behind reverse proxy)
COPY nginx.proxy.conf /etc/nginx/nginx.conf

# Copy built files
COPY --from=builder /app/dist /usr/share/nginx/html

# Runtime branding: regenerate /brand-config.js from BRAND_* env on startup.
# nginx:alpine runs /docker-entrypoint.d/*.sh before launching nginx, so a plain
# `docker compose up -d frontend` re-brands the same image without a rebuild.
COPY docker-entrypoint.d/10-brand.sh /docker-entrypoint.d/10-brand.sh
RUN chmod +x /docker-entrypoint.d/10-brand.sh

# Runtime feature flags: regenerate /feature-config.js from FEATURE_* env on
# startup — same no-rebuild switch mechanism as branding above.
COPY docker-entrypoint.d/20-features.sh /docker-entrypoint.d/20-features.sh
RUN chmod +x /docker-entrypoint.d/20-features.sh

# Expose port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost/ || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]


# Development stage
FROM node:20-alpine AS development

WORKDIR /app

# Same optional proxy as the builder stage (see above).
ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY="localhost,127.0.0.1"
ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    no_proxy=${NO_PROXY}

# Copy package files
COPY package.json package-lock.json* yarn.lock* pnpm-lock.yaml* ./

# Install dependencies
RUN npm install

# Copy source files
COPY . .

# Expose Vite dev server port
EXPOSE 5173

# Start development server
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
