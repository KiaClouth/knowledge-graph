# 远程部署清单 —— kg.kiaclouth.com

个人知识/能力图谱 MCP server 上 Ubuntu 服务器。全 Docker + 复用现有 nginx(certbot
TLS)+ Bearer token 鉴权。Neo4j 与 MCP 都只绑回环,唯一入口是 nginx。

前置:服务器已装 Docker/compose、nginx、certbot;7687/8000 空闲;dasuapi 与智谱端点可达。

--------------------------------------------------------------------------------
## 步骤 0 —— DNS(先做,证书签发要等它生效)
给 kg.kiaclouth.com 加一条 A 记录,指向本服务器公网 IP(与 app/test 同一台)。
验证(等生效,可能几分钟到几十分钟):
    dig +short kg.kiaclouth.com          # 应返回服务器公网 IP

--------------------------------------------------------------------------------
## 步骤 1 —— 取代码
本仓库在 GitHub: KiaClouth/knowledge-graph。先在本地把最新 commit push 上去
(部署改动都在里面),再到服务器 clone:

    # 服务器上:
    cd ~
    git clone https://github.com/KiaClouth/knowledge-graph.git
    cd knowledge-graph/mcp_server

--------------------------------------------------------------------------------
## 步骤 2 —— 填密钥
    cp deploy/.env.example deploy/.env
    # 编辑 deploy/.env,填:
    #   NEO4J_PASSWORD   —— openssl rand -hex 16
    #   OPENAI_API_KEY   —— dasuapi key
    #   EMBEDDER_API_KEY —— 智谱 key
    #   KG_BEARER_TOKEN  —— openssl rand -hex 32(客户端也要用这个)
    nano deploy/.env

生成随机值参考:
    echo "NEO4J_PASSWORD=$(openssl rand -hex 16)"
    echo "KG_BEARER_TOKEN=$(openssl rand -hex 32)"

--------------------------------------------------------------------------------
## 步骤 3 —— 起 Docker(Neo4j + MCP)
    docker compose -f deploy/docker-compose.remote.yml --env-file deploy/.env up -d --build

检查:
    docker compose -f deploy/docker-compose.remote.yml ps       # 两个都 healthy
    docker logs kg-mcp --tail 30                                 # 看到 "streamable HTTP" 启动日志
    curl -s http://127.0.0.1:8000/health                        # {"status":"healthy",...}

首次构建会拉基础镜像 + uv lock/sync,耗时数分钟。Neo4j 首次 healthy 约 30s。

--------------------------------------------------------------------------------
## 步骤 4 —— 签 TLS 证书(nginx 插件,自动改配置)
先确保 DNS 已生效(步骤 0)。用 certbot 的 nginx 插件签发:

    sudo certbot certonly --nginx -d kg.kiaclouth.com

(或 --webroot,看你现有 app/test 怎么签的就照用。证书落在
 /etc/letsencrypt/live/kg.kiaclouth.com/)

--------------------------------------------------------------------------------
## 步骤 5 —— 装 nginx vhost(带 Bearer 鉴权)
把 token 填进 vhost,再启用:

    # 用 deploy/.env 里的 KG_BEARER_TOKEN 替换占位符,生成正式 vhost:
    TOKEN=$(grep '^KG_BEARER_TOKEN=' deploy/.env | cut -d= -f2)
    sudo sed "s/<PUT-YOUR-TOKEN-HERE>/$TOKEN/" deploy/nginx.kg.conf \
        | sudo tee /etc/nginx/sites-available/kg.kiaclouth.com >/dev/null
    sudo ln -sf ../sites-available/kg.kiaclouth.com /etc/nginx/sites-enabled/kg.kiaclouth.com

    sudo nginx -t && sudo systemctl reload nginx

--------------------------------------------------------------------------------
## 步骤 6 —— 冒烟验证(从服务器本机)
    # 无 token → 401
    curl -s -o /dev/null -w "%{http_code}\n" https://kg.kiaclouth.com/mcp/
    # 带 token → 非 401(MCP 端点对裸 GET 可能返回 400/406,但过了鉴权即证 OK)
    curl -s -o /dev/null -w "%{http_code}\n" \
        -H "Authorization: Bearer $TOKEN" https://kg.kiaclouth.com/mcp/
    # health 匿名可达
    curl -s https://kg.kiaclouth.com/health

--------------------------------------------------------------------------------
## 步骤 7 —— 客户端接入(各机器的 Claude Code / Codex)
把这个 server 配成 HTTP transport 的 MCP,URL 指向 https://kg.kiaclouth.com/mcp/,
带 Authorization: Bearer <KG_BEARER_TOKEN>。示例(Claude Code .mcp.json 片段):

    {
      "mcpServers": {
        "kg": {
          "type": "http",
          "url": "https://kg.kiaclouth.com/mcp/",
          "headers": { "Authorization": "Bearer <KG_BEARER_TOKEN>" }
        }
      }
    }

验证:让 agent 调 add_memory(记得传 source="message" 喂第一人称对话体,
形如 "User: 我用X做了Y"),再调 search_nodes / search_memory_facts 读回。

--------------------------------------------------------------------------------
## 运维
- 看日志:    docker logs kg-mcp -f   /   docker logs kg-neo4j -f
- 重启:      docker compose -f deploy/docker-compose.remote.yml --env-file deploy/.env restart
- 更新代码:  git pull && docker compose -f deploy/docker-compose.remote.yml --env-file deploy/.env up -d --build
- 停:        docker compose -f deploy/docker-compose.remote.yml --env-file deploy/.env down
- 数据在具名卷 kg_neo4j_data,down 不会删;要清库加 -v(谨慎)。

## 安全备注
- Neo4j(7687/7474)与 MCP(8000)都只绑 127.0.0.1,公网碰不到;唯一入口是 nginx。
- 换 token:改 deploy/.env 的 KG_BEARER_TOKEN → 重跑步骤 5 的 sed+reload → 更新所有客户端。
- 建议 ufw 只放行 22/80/443:sudo ufw allow 22,80,443/tcp && sudo ufw enable
- EMBEDDER_DIM=2048 首次写入即固化进 Neo4j schema,别中途改。
