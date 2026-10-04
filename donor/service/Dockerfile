FROM node:22-alpine

WORKDIR /code

COPY package.json ./package.json
COPY src ./src

ENV NODE_ENV=production
EXPOSE 4739

USER node

CMD ["node", "src/index.js"]
