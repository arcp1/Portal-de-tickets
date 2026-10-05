# Stage 1: Build
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# Stage 2: Serve with NGINX
# Fijada, igual que el nginx de compose: con `alpine` a secas cada build podía
# traer otro nginx sin que nadie lo decidiera ni lo revisara.
FROM nginx:1.31.4-alpine

COPY --from=build /app/dist /usr/share/nginx/html
# Fallback a index.html para las rutas de React Router.
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
