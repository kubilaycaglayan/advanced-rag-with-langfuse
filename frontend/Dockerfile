FROM node:22-alpine AS build
WORKDIR /frontend
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html tsconfig.json vite.config.ts ./
COPY src/ ./src/
RUN npm run build

FROM node:22-alpine
ENV NODE_ENV=production FRONTEND_PORT=43179
WORKDIR /frontend
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY server.js ./
COPY --from=build /frontend/dist ./dist
EXPOSE 43179
CMD ["node", "server.js"]
