# Draw.io MCP 服务（PPT 视觉增强层）

PPT 工作台会先尝试 drawio-mcp 的 `create_diagram`。该工具接受 Mermaid，
但官方 app-server 返回 Mermaid 源码，由 MCP Apps 查看器在客户端转换，
不会向本平台后端返回排版后的 XML。因此此时自动使用本地 Graphviz `dot`
布局，再将 XML 转成 PPTX 中可编辑的原生形状、文字和连接线。
若 MCP 将来直接返回 XML，后端会验证节点和连线并使用该结果。

官方镜像 [`jgraph/drawio-mcp`](https://hub.docker.com/r/jgraph/drawio-mcp)（Apache-2.0，
已构建 amd64 + arm64），与 `https://mcp.draw.io/mcp` 是同一套代码。

## 边界（先读）

- **只产出文本型工具结果**，不产出 `.pptx`。它提供：
  - `get_drawio_reference` —— draw.io XML/Mermaid 语法参考（模型在画第一张图前读一次）；
  - `search_shapes` —— 跨上千个 shape 库按关键词检索，返回可直接塞进 XML 的 `style` 字符串；
  - `create_diagram` —— Mermaid 模式的当前结果是源码及查看链接，排版在 MCP Apps
    查看器内完成。只有工具直接返回可解析、可校验的 XML，后端才能将其用于 PPTX。
- 原生转换由 `server/app/application/ppt/drawio_native.py` 完成，支持矩形、圆角矩形、
  椭圆、菱形、文本及节点连线；单页最多 40 个节点和 40 条连线。图片、自定义图标、
  嵌套分组、压缩页面会明确拒绝，生成失败时原页面保持不变。
- MCP 本身不导出 PPTX；本平台的转换器负责生成可编辑对象。`dot` 和 MCP 都
  不可用时，使用本地基础步骤版式。此变更不需要 PPTAgent。
- 已配置 MCP 但临时不可达或未返回参考时，自动调用本地 `ai_generate_visual`，
  成功响应附 `warnings` 提示回退。模型返回非法图示 XML 时继续报错并保留原页面；
  本地生成本身失败时也保留正常错误，不伪造成功结果。
- 导出已有文稿时，如某页图示损坏或绘制失败，仅该页改用基础流程版式；
  先撤销本次未完成图形，再填入原流程内容。生成接口返回 `warnings`，
  导出文件的该页演讲备注也记录回退提示及原流程内容，其余页面继续导出。
- 服务**无鉴权**。内网部署靠防火墙 / 反向代理 / 端口绑回环控制可达范围。
- 内网不出网：`search_shapes` 默认会补查 `icons.diagrams.net`，必须设
  `DRAWIO_ICON_SERVICE_URL=off` 关闭（`icons.diagrams.net` 也未必能出网）。

## 部署

```bash
cd deploy/drawio-mcp
docker compose up -d
# 探活
curl -fsS http://localhost:3001/health   # 或 GET /health → 200 ok
```

- MCP 端点：`http://<宿主IP>:3001/mcp`（Streamable HTTP；`DRAWIO_MCP_URL` 只填 `http://<宿主IP>:3001`，客户端自动补 `/mcp`）。
- 容器内端口默认 `3001`（镜像 `PORT` 默认值，可改）。
- 镜像基于 Node，容器内无 `curl`/`wget`；compose 的 healthcheck 用 `node -e fetch` 探活。

## 接入后端（API 容器）

在 API 容器的环境里设：

```
DRAWIO_MCP_URL=http://drawio-mcp:3001   # docker 网络内用服务名（base，客户端自动补 /mcp）
DRAWIO_MCP_TIMEOUT=30
```

- 留空 `DRAWIO_MCP_URL` → 后端 `DrawioService` 自动判定未启用，PPT 流程图仍走本地
  原生渲染，**零侵入**。
- 后端客户端见 `server/app/infrastructure/drawio/mcp_client.py`；
  服务封装见 `server/app/application/ppt/drawio_service.py`。

## 跨 compose 网络互通

`deploy/production.docker-compose.yml` 的 `justice-net` 与本 compose 的 `justice-net`
同名但默认各自独立。要让生产 API 容器能访问 `drawio-mcp` 服务名，二选一：

1. 把本 compose 的 `networks.justice-net` 改为 `external: true`，并指向生产已建网络
   （`docker network inspect justice-net` 确认存在）；或
2. 在生产 compose 里直接 `docker network connect justice-net justice-drawio-mcp`
   把本容器挂到生产网络，再用服务名访问。

生产不发布 3001 端口给宿主机外部，仅容器间通信即可。

## 环境变量

| 变量 | 作用 | 默认 |
| :--- | :--- | :--- |
| `PORT` | 容器内监听端口 | `3001` |
| `DRAWIO_ICON_SERVICE_URL` | 设为 `off` 关闭图标服务出网查询 | （查 `icons.diagrams.net`） |
| `ALLOWED_HOSTS` | 按 Host 头限制接受的主机名（逗号分隔无空格） | 不限制 |

## 排障

- 服务起不来 / 端口冲突：改 `ports` 映射或 `PORT`。
- `search_shapes` 超时：确认 `DRAWIO_ICON_SERVICE_URL=off`（内网无 `icons.diagrams.net`）。
- 后端连不上：确认 `DRAWIO_MCP_URL` 用的是**容器间可达地址**（docker 网络内用服务名
  `drawio-mcp:3001`，宿主机直连用 `http://<宿主IP>:3001`），而非 `127.0.0.1`；客户端会自动补 `/mcp`。
