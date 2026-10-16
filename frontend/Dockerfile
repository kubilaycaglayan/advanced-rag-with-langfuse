# Build from the repository's frontend/ directory with the ui submodule checked out
# (git submodule update --init).
FROM node:22-alpine AS build
WORKDIR /frontend/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN STATIC_SPA=true npm run build

FROM node:22-alpine
ENV NODE_ENV=production FRONTEND_PORT=43179
WORKDIR /frontend
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY server.js ./
COPY --from=build /frontend/ui/dist/client ./ui/dist/client
EXPOSE 43179
CMD ["node", "server.js"]
