# ---- 构建阶段：node 里把前端源码编译成静态文件 ----
FROM node:20-alpine AS build

WORKDIR /app

# 先只拷贝依赖清单，命中缓存时跳过重复安装
COPY package.json package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com

COPY . .
RUN npm run build


# ---- 运行阶段：nginx 只负责发静态文件 + 反代后端 ----
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 5173

CMD ["nginx", "-g", "daemon off;"]
