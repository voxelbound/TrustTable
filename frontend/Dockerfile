# TrustTable frontend image (FND-01, repository-foundation stage).
#
# Multi-stage build: compile the production Vite/React bundle, then serve
# the static assets with Nginx (non-root by default via the
# "nginx-unprivileged" base image) with an /api/v1 reverse proxy and SPA
# fallback. No product screens exist at this stage.

FROM node:24.19-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080
