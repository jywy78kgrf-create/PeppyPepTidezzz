# ATLAS frontend — build static bundle, serve via nginx with /api proxy
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# empty base URL -> all API calls are relative (/api/...), proxied by nginx
ENV VITE_API_URL=""
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
