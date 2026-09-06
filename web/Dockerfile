FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
# vite.config.ts reads process.env.VITE_BASE_PATH directly (Node-side, at
# config-eval time) — Vite's own .env auto-loading doesn't populate
# process.env for the config file itself, so .env.production is sourced
# into the shell explicitly (matches insurance-web/Dockerfile's exact
# convention — OpenChoreo's dockerfile-builder has no build-args
# mechanism, so build-time config is committed here, not passed as ARGs).
RUN set -a && . ./.env.production && set +a && npm run build

FROM nginx:1.27-alpine
# Matches VITE_BASE_PATH in .env.production.
COPY --from=build /app/dist /usr/share/nginx/html/job-search-web-ui
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
