# 方案B部署：前端 GitHub Pages + 后端 Render

## 1) 后端部署到 Render

- 新建 `Web Service`，连接当前 GitHub 仓库
- Runtime 选 `Python`
- Start Command:

```bash
python3 serve.py
```

Render 会自动注入 `PORT`，`serve.py` 已支持读取该变量。

## 2) Render 环境变量

至少配置以下变量：

- `LLM_API_BASE`（例：`https://api.deepseek.com/v1`）
- `LLM_API_KEY`（你的真实密钥）
- `LLM_MODEL`（例：`deepseek-chat`）
- `CORS_ALLOW_ORIGIN`（建议填你的 Pages 域名，例：`https://aimepython.github.io`）

## 3) 前端连接后端

GitHub Pages 首页默认调用同源 `/api/ask`。  
方案B下可通过 URL 参数指定后端地址：

```text
https://<你的pages域名>/index.html?api_base=https://<你的render域名>
```

例如：

```text
https://aimepython.github.io/yuedubaogao/index.html?api_base=https://market-agent.onrender.com
```

## 4) 验证

- 后端健康检查：
  - `https://<你的render域名>/api/health`
- 前端提问：
  - 在上述带 `api_base` 的 Pages 链接中提问
  - 若正常，返回答案并含来源链接

## 5) 安全建议

- 不要提交 `.env` 到仓库
- 发现密钥泄露时立即在平台后台轮换
