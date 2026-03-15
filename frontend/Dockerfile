FROM node:22-alpine AS build

WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Railway sets PORT; BACKEND_URL should point to the backend service
ENV PORT=3000
ENV BACKEND_URL=http://backend:8000

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
