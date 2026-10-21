# VPS 基础设施启动指南

四个容器：MariaDB 11.4（业务库）、PostgreSQL 17（LangGraph checkpointer）、Redis 7（队列 + 事件广播）、Redis Commander（运维面板，宿主 7741）。
本目录产物在 M1 之前即可独立运行，不依赖任何应用代码。

## 1. 前置条件

- VPS 已装 Docker 与 compose 插件：`docker --version && docker compose version`
- 磁盘 ≥ 10 GB（三个库的空数据量很小，主要是镜像与日志）
- 内存 ≥ 2 GB。小于 2 GB 时把 `docker-compose.yml` 里 `--innodb-buffer-pool-size=512M` 调到 `256M`

## 2. 启动

```bash
# 上传整个 deploy 目录后
cd deploy
cp .env.example .env

# 生成强密码并写进 .env（示例；每个密码单独生成一次）
openssl rand -base64 24 | tr -d '/+=' | cut -c1-24

vi .env            # 改 MARIADB_PASSWORD / MARIADB_ROOT_PASSWORD / POSTGRES_PASSWORD / REDIS_PASSWORD / REDIS_COMMANDER_PASSWORD

docker compose up -d
docker compose ps  # 三库应为 healthy；redis-commander 为 Running（该镜像无健康检查）
```

只启动基础设施（文件里将来追加 api/worker/frontend 后仍然适用）：

```bash
docker compose up -d mariadb postgres redis
```

## 3. 验收（逐条执行，期望输出已写明）

```bash
# 1) 容器状态：STATUS 列应为 Up (healthy)
docker compose ps

# 2) MariaDB 版本与字符集：期望 11.4.x / utf8mb4 / utf8mb4_unicode_ci
docker compose exec mariadb sh -c \
  'mariadb -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE" \
   -e "select version(), @@character_set_database, @@collation_database;"'

# 3) 中文 + emoji 落库（期望插入成功且回显正常）
docker compose exec mariadb sh -c \
  'mariadb -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE" \
   -e "create table if not exists _charset_probe(v varchar(32)) default charset=utf8mb4 collate=utf8mb4_unicode_ci;
       insert into _charset_probe values (\"中文😀\");
       select v, char_length(v), length(v) from _charset_probe;
       drop table _charset_probe;"'
# 期望 char_length=3（中文😀 三个字符）、length=10（UTF-8 字节数 3+3+4）

# 4) PostgreSQL：期望 version 17.x，库名 devpipeline_graph
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select version();"

# 5) Redis：期望 PONG
docker compose exec redis sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping'

# 6) Redis Commander：不带凭据 401，带凭据 200
curl -s -o /dev/null -w '%{http_code}\n' http://<host>:7741/
curl -s -o /dev/null -w '%{http_code}\n' -u "$REDIS_COMMANDER_USER:$REDIS_COMMANDER_PASSWORD" http://<host>:7741/
```

从你自己机器再验一次端口可达（把 host/port 换成实际值）：

```bash
nc -vz <host> 13306 && nc -vz <host> 15432 && nc -vz <host> 16379 && nc -vz <host> 7741
```

## 4. 暴露方式（二选一）

### 方式 A：公网直连（默认，端口 13306/15432/16379，面板 7741）

- VPS 安全组 / ufw **只放行你自己的出口 IP**，不要 `0.0.0.0/0`：
  ```bash
  ufw allow from <你的出口IP> to any port 13306 proto tcp
  ufw allow from <你的出口IP> to any port 15432 proto tcp
  ufw allow from <你的出口IP> to any port 16379 proto tcp
  ufw allow from <你的出口IP> to any port 7741 proto tcp
  ```
- 已知风险：官方镜像不带 TLS，三个库都是**明文连接**。安全性依赖「强密码 + IP 白名单」。要 TLS 需另配证书与 `sslmode=require`，本期不做。
- **Redis Commander 必须带 basic auth**：不设 `REDIS_COMMANDER_USER` / `REDIS_COMMANDER_PASSWORD` 时它没有任何鉴权，公网任何人都能浏览、改写 Redis（实测未设时直接返回 200）。面板只给自己看，建议改绑 `127.0.0.1` 走隧道，或至少 ufw 白名单 + 强密码。

### 方式 B：完全不对公网 + SSH 隧道（更安全）

```bash
# .env 改成 BIND_ADDR=127.0.0.1 后 docker compose up -d
ssh -N -L 13306:127.0.0.1:13306 -L 15432:127.0.0.1:15432 -L 16379:127.0.0.1:16379 -L 7741:127.0.0.1:7741 <user>@<vps>
# 之后本地一律连 127.0.0.1:13306 / 15432 / 16379，面板走 http://127.0.0.1:7741
```

## 5. 回填到本地项目

`backend/.env` 已按下面的模板从 `deploy/.env` 派生生成（Git 已忽略，含真实密码与自动生成的 `APP_SECRET_KEY`）。换机器时照此模板重建：

```dotenv
# MariaDB（业务库）
MARIADB_HOST=<vps-host>
MARIADB_PORT=13306
MARIADB_USER=devpipeline
MARIADB_PASSWORD=<MARIADB_PASSWORD>
MARIADB_DATABASE=devpipeline

# PostgreSQL（只放 LangGraph checkpointer）
POSTGRES_HOST=<vps-host>
POSTGRES_PORT=15432
POSTGRES_USER=devpipeline
POSTGRES_PASSWORD=<POSTGRES_PASSWORD>
POSTGRES_DB=devpipeline_graph
# checkpointer 用 psycopg 连接池（pipeline 模式与连接池互斥，不要开）


# Redis（arq 队列 + 事件广播）
REDIS_HOST=<vps-host>
REDIS_PORT=16379
REDIS_PASSWORD=<REDIS_PASSWORD>
REDIS_DB=0
# 队列后端：arq（Redis 队列，M3 起正式路径；需同时起 worker）/ inline（进程内，零依赖）
QUEUE_BACKEND=arq

# LLM（DeepSeek，OpenAI 兼容）
LLM_KEY_DEEPSEEK=<你的 key>
```

LLM 的「配置 → 运行时参数」对照（配置沿用项目既有写法）：

```python
LLM_PROVIDERS = {
    'deepseek-v4-flash': {
        'model': 'deepseek-flash',
        'url': 'https://api.deepseek.com/chat/completions',
        'key': env.llm_key_deepseek,   # 即环境变量 LLM_KEY_DEEPSEEK
    },
}
# 运行时 ChatOpenAI(base_url=url.removesuffix('/chat/completions'), api_key=key, model=model)
# 注意：url 是完整 endpoint，base_url 必须剥掉 /chat/completions，
#       否则 SDK 会拼成 /chat/completions/chat/completions → 404
```

## 6. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `port is already allocated` | VPS 上端口被占用：改 `.env` 里的 `*_HOST_PORT`，或 `ss -lntp \| grep <port>` 查占用 |
| 容器 `Up` 但一直 `unhealthy` | 密码里有 `$`、`"`、空格导致 healthcheck 取不到；重新生成仅字母数字的密码后 `docker compose up -d --force-recreate` |
| 本地 `nc` 通、程序连不上 | 服务端 bind 到了 127.0.0.1（方式 B），本地必须走隧道；或安全组放行的是别的 IP |
| 字符集不是 `utf8mb4_unicode_ci` | 数据目录非空时 initdb 脚本不会执行：`docker compose down -v` 会**清空数据**，确认空库后重建 |
| 中文乱码 | 连接串未带 `charset=utf8mb4`（MariaDB）或客户端 locale 问题，先按第 3 节验收 |
| 忘记密码 | 只能改 `.env` 后 `docker compose down -v` 重建（数据清空）；或进容器用 root 改 `ALTER USER` |

## 7. 备份与升级

```bash
# 备份（按需加 cron）
docker compose exec mariadb sh -c 'mariadb-dump -u root -p"$MARIADB_ROOT_PASSWORD" --single-transaction devpipeline' > mariadb-$(date +%F).sql
docker compose exec postgres pg_dump -U devpipeline devpipeline_graph > pg-$(date +%F).sql
docker compose exec redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning BGSAVE

# 版本升级前先备份，再 docker compose pull && docker compose up -d
```

数据在命名卷 `mariadb-data` / `postgres-data` / `redis-data` 中，`docker compose down`（不带 `-v`）不会删数据。
