FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

FROM node:20-slim
WORKDIR /app
ENV NODE_ENV=production
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/dist ./dist

# Baked at build time — never read from a mutable file or set at runtime.
ARG GIT_COMMIT
ENV GIT_COMMIT=${GIT_COMMIT}
ENV PORT=8080

EXPOSE 8080
CMD ["node", "dist/server.js"]
