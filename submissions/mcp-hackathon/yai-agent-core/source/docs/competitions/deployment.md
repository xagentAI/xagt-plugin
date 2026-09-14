# 公网部署手册（X-Agent 硬门槛落地指南）

> 最后核实：2026-09-10。免费政策变化快，动手前点文末来源链接复核。
> 目标：让 `https://<你的域名>/health` 等四个端点公网可访问，且返回的 commit 与提交 PR 里的 pinned commit 完全一致。

## 0. 要满足的硬门槛（对应 X-Agent 7 项硬门槛中的部署部分）

| 门槛 | 本项目落地方式 |
|---|---|
| 已部署、公网可调用的 API | Docker Compose 常驻 VPS，Caddy 反代 443 |
| `GET /health` 返回 status + 40 位 commit | Battery 已实现；commit 构建时由 `--build-arg YAI_GIT_COMMIT` 固化 |
| `/.well-known/xagent-verification.json` 同源同 commit | Battery 已实现，与 /health 读同一个环境变量 |
| pinned commit | 部署哪个 commit，PR 的 `source/` 就放哪个 commit 的源码 |
| 可复现说明 | 本手册 + README 的两条 compose 命令 |

## 1. 免费方案选型（2026-09 官方页面核实）

| 方案 | 成本 | 是否常驻 | HTTPS 与域名 | 结论 |
|---|---|---|---|---|
| **Oracle Cloud Always Free** | 永久免费：2 台 AMD micro（1/8 OCPU、1GB）+ ARM Ampere A1（总量最多 4 OCPU/24GB，可开 1-2 台）、200GB 块存储、约 10TB/月出站流量 | 常驻不休眠 | 自备域名（免费 DuckDNS 即可），Caddy 自动签证书 | **正式部署首选** |
| Google Cloud e2-micro | 永久免费 1 台（限定美国 3 个区，1GB） | 常驻 | 同上 | 备选，注册同样要卡 |
| Render Free Web Service | 免费 | **15 分钟无流量休眠，冷启动约 30–90 秒（波动大）**；750 实例小时/月 | 自带 `*.onrender.com` 证书 | **今天做演练用**，评审期有被休眠打到的风险 |
| Fly.io | 无免费层，shared-cpu-1x 256MB 约 $3.14/月起 | 常驻 | 自带 `*.fly.dev` 证书 | 不想折腾 Oracle 时的便宜替代 |
| Koyeb | 免费实例已取消（官网只剩付费计划） | — | — | 排除 |
| Hugging Face Spaces | Docker/Gradio Space 创建已需付费计划；免费硬件会休眠 | 休眠 | 自带 | 排除 |
| 阿里云/腾讯云学生机 | 约 ¥10/月级 | 常驻 | **大陆机房域名走 443 需 ICP 备案（赶不上 09-19/10-04）**；海外地域免备案但学生价通常限大陆地域 | 不推荐用于本次比赛 |

**建议路线**：今天先用 **Render 免费层 30 分钟拿到公网 HTTPS 地址**跑通全流程；正式提交前迁到 **Oracle Always Free + Caddy** 常驻。我们的服务只是转发到 DeepSeek，本机不跑模型，AMD 1GB 小机器都够用。

## 2. 路线 A：Render 免费层快速演练（零成本、约 30 分钟）

仓库根目录已放好 `render.yaml`（Render Blueprint），平台名、端口、健康检查、非敏感变量都已声明，
只需在网页上连接仓库并粘贴一次 Key：

1. 打开 https://render.com → 用 GitHub 账号登录并授权访问 `Gi-Tuu/yai-agent-core`。
2. 控制台 **New → Blueprint**，选择 `yai-agent-core` 仓库，Render 会读取 `render.yaml`
   自动生成一个 Free 的 Docker Web Service（区域 Singapore，健康检查路径 `/health`）。
3. Blueprint 向导会提示填写标记为 `sync: false` 的 Secret：`OPENAI_API_KEY` = DeepSeek Key，粘贴即可。
   其余变量（`OPENAI_BASE_URL`、`LLM_MODEL`、`YAI_PROJECT_SLUG` 等）已在 yaml 里写好。
4. 点 **Apply / Deploy**，云端开始构建（海外环境用官方 PyPI，不需要 `INDEX_URL`）。
5. 两个自动化约定（已在代码里处理，无需手动操作）：
   - **端口**：Render 注入 `PORT`（默认 10000），Dockerfile 的 CMD 是
     `--port ${PORT:-8000}`，本地/compose 仍是 8000，上了 Render 自动跟随；
   - **commit**：Render 自动注入 `RENDER_GIT_COMMIT`（本次部署的完整 SHA），
     `serve_example.py` 的解析链 `YAI_GIT_COMMIT → RENDER_GIT_COMMIT → git HEAD → dev`
     会自动采用它，/health 与验证端点返回的 commit 天然等于部署的 commit。
     注意解析时只接受完整 40 位小写哈希——镜像里烤的默认值 `dev` 不是合法哈希会被跳过
     （首部署实测：若不跳过，非空的 `dev` 会遮蔽平台注入的真实 SHA）。
6. 部署完成后得到 `https://yai-agent-core.onrender.com`（名字以实际为准），按第 4 节验证四个端点。
7. 风险：15 分钟无流量会休眠，评审机第一次访问可能撞上约 30–90 秒冷启动页（不是我们的 JSON）。
   **正式评审前必须换到常驻 VPS。**

> 若不用 Blueprint、手动 New → Web Service：Language 选 Docker、Dockerfile Path 留空（根目录）、
> Plan 选 Free，然后在 Environment 里补齐上面同样的变量即可，效果相同。

## 3. 路线 B：Oracle Always Free + Docker + Caddy（正式部署）

### 3.1 注册与开机器
1. 在 https://www.oracle.com/cloud/free/ 注册（需一张信用卡/借记卡做验证，不扣款；一人一号，信息真实）。
2. Home Region **一旦选定不可更改**，建议 Tokyo / Seoul / Singapore（离大陆近、PyPI 与 DeepSeek 都通）。
3. Create Instance：
   - Image：Ubuntu 24.04
   - Shape：优先 `VM.Standard.A1.Flex`（ARM，给 1 OCPU/6GB 即可，抢不到容量就用 `VM.Standard.E2.1.Micro`，AMD 1GB 也能跑）
   - 保存 SSH 私钥（页面可自动生成并下载）
4. VCN 安全列表（Security List）放行入站：tcp 80、tcp 443；tcp 22 建议只放行你自己的出口 IP。

### 3.2 装 Docker（SSH 上去后）
```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker ubuntu   # 重新登录后免 sudo
```

### 3.3 拉代码、配环境、起服务
```bash
git clone https://github.com/Gi-Tuu/yai-agent-core.git
cd yai-agent-core
cp .env.example .env
nano .env          # 填 OPENAI_API_KEY、YAI_PROJECT_SLUG；YAI_GIT_COMMIT 保持注释
nano deploy/Caddyfile   # 把域名换成你的（见 3.4）

git rev-parse HEAD   # 记下这 40 位 commit，X-Agent 提交 PR 时用同一个
YAI_GIT_COMMIT=$(git rev-parse HEAD) \
  docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d --build
```
说明：
- 基础 compose 只把容器端口绑在 `127.0.0.1:8001`（本机调试用），公网只能经 Caddy 进入；
- deploy 叠加文件启动 Caddy，占用 80/443，首次请求时自动向 Let's Encrypt 申请证书并自动续期；
- ARM 机器无需改 Dockerfile，`python:3.13-slim` 有 arm64 镜像；
- 海外 VPS 构建用官方 PyPI 即可；若网络抽风，构建时加 `INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`。

### 3.4 免费域名（DuckDNS，不用买域名）
1. 打开 https://www.duckdns.org/ ，用 GitHub/Google 登录；
2. 新建子域名（如 `yai-agent-core`），把 A 记录填成 VPS 公网 IP；
3. 把 `deploy/Caddyfile` 改成：
   ```
   yai-agent-core.duckdns.org {
       reverse_proxy yai-agent-core:8000
   }
   ```
4. `docker compose -f docker-compose.yml -f docker-compose.deploy.yml restart caddy`，
   首次 HTTPS 访问时 Caddy 自动签好证书（`docker compose logs caddy` 可看到证书申请记录）。

### 3.5 更新版本（比赛迭代时反复用）
```bash
git pull
YAI_GIT_COMMIT=$(git rev-parse HEAD) \
  docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d --build
```
重新构建后 /health 的 commit 自动变成新版本——**每次重新部署，X-Agent PR 里的 pinned commit 也要同步更新**。

## 4. 部署后验证清单（在自己电脑上跑）

```bash
BASE=https://<你的域名>
curl $BASE/health                                 # 期望 {"status":"ok","commit":"<40位>"}
curl $BASE/.well-known/xagent-verification.json   # 期望 schemaVersion/slug/commit，commit 与上面一致
curl $BASE/v1/tools                                # 期望工具清单
curl -X POST $BASE/v1/agent/run -H "Content-Type: application/json" \
  -d '{"task":"列出我的全部笔记"}'                  # 期望 strategy/events/final_text
docker compose ps                                   # caddy 与 app 均 healthy
```
四项全过 = X-Agent 部署类硬门槛达标。

- [x] `YAI_DB_PATH`：Render Blueprint 已默认开启（`data/yai.db` → 容器内 `/app/data`，启动时自动建目录）；本地/容器不设置该变量时仍是进程内内存。
  **Render 免费层是临时盘，redeploy 后会丢库**：重建后历史清空属预期行为，对外演示口径需如实说明；VPS 形态请把该路径放在挂载卷上。

## 5. 安全与运维清单

- `.env` 只存在于服务器，不进 git、不进镜像（`.dockerignore` 已排除）；
- 安全组只开 22/80/443，容器端口不直接对公网开放（已绑回环）；
- Caddy 证书数据在 `caddy-data` 卷里，重启不丢、自动续期；
- 模型调用全部出站到 DeepSeek 云端，VPS 不跑模型，CPU/内存压力很小；
- 若海外 VPS 访问 `api.deepseek.com` 异常，先 `curl https://api.deepseek.com` 排查，必要时换 Oracle 区域（待首次部署实测）。

## 6. 参考来源（官方）

- Oracle Cloud Free Tier：https://www.oracle.com/cloud/free/
- Render Free 限制（休眠/750 小时）：https://render.com/docs/free
- Render Docker 部署（PORT/构建参数）：https://render.com/docs/docker
- Render 注入的环境变量（RENDER_GIT_COMMIT）：https://render.com/docs/environment-variables
- Render Blueprint（render.yaml）：https://render.com/docs/blueprint-spec
- Fly.io 定价（无免费层）：https://fly.io/docs/about/pricing/
- Koyeb 定价（免费实例已取消）：https://www.koyeb.com/pricing
- Hugging Face Spaces（Docker Space 需付费）：https://huggingface.co/docs/hub/spaces-overview
- Caddy 文档（自动 HTTPS）：https://caddyserver.com/docs/
- DuckDNS 免费域名：https://www.duckdns.org/
