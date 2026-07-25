# 玄策·天机 MVP

这是一个可本地运行、也可直接部署到 Vercel 的 DeepSeek 分析原型，包含两个入口：

- 自我分析
- 多朋友关系分析

## 运行

```bash
cd /Users/admin/2026全战役/全模型战役
python3 server.py
```

打开：

```text
http://127.0.0.1:8000
```

## Vercel 部署

1. 把这个目录推到 GitHub。
2. 在 Vercel 导入该仓库。
3. 在 Vercel 项目环境变量里添加 `DEEPSEEK_API_KEY`。
4. 如需自定义模型，也可加 `DEEPSEEK_MODEL`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_REASONING_EFFORT`。
5. 部署后先确认 Vercel 分配的 `*.vercel.app` 域名可访问。
6. 在 Vercel 项目 Settings -> Domains 中添加：
   - `fatelinkmodel.com`
   - `www.fatelinkmodel.com`
7. 在域名 DNS 面板中添加 Vercel 要求的记录。通常为：
   - `@` / `A` / `76.76.21.21`
   - `www` / `CNAME` / `cname.vercel-dns-0.com`
8. Vercel Domains 页面显示 Valid Configuration 后，会自动签发 HTTPS 证书。

当前域名：`fatelinkmodel.com`。

注意：Vercel 项目页面可能会给出项目专属 CNAME。以 Vercel Domains 页面展示的记录为准。

## DeepSeek

后端会优先从以下位置读取 API Key：

1. 环境变量 `DEEPSEEK_API_KEY`
2. `../API KEY.rtf`
3. 环境变量 `DEEPSEEK_API_KEY_FILE`

默认模型使用 `deepseek-v4-pro`，并开启思考模式。

## 说明

- 前端输入会自动缓存到浏览器本地存储。
- 所有分析必须由 DeepSeek 深度思考返回；如果 DeepSeek 请求失败，页面会显示真实错误，不生成本地兜底结果。
- 关系分析只输出透明、可拒绝、可退出的建议，不提供操控或隐蔽推进策略。
- Vercel 版本通过 `api/analyze.py` 和 `api/health.py` 暴露接口，静态页直接由根目录的 `index.html`、`app.js`、`styles.css` 提供。
