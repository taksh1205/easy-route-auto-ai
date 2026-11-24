FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build && chown -R node:node /app
USER node
CMD ["npm","start","--","--hostname","0.0.0.0"]
