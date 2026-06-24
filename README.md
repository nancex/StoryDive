# StoryDive 快速启动指南

## 环境要求

- Python 3.10+
- 现代浏览器（Chrome / Edge / Firefox）

## 1. 安装依赖

```powershell
cd F:\.workspace\StoryDive

# 创建虚拟环境（首次）
python -m venv .venv

# 激活并安装
.\.venv\Scripts\activate
pip install -r backend\requirements.txt
```

## 2. 启动后端

```powershell
.\.venv\Scripts\python.exe backend\server.py
```

服务运行在 `http://localhost:8800`

## 3. 打开前端

直接用浏览器打开 `frontend\index.html`，或在终端执行：

```powershell
start frontend\index.html
```

## 4. 配置 LLM API（可选）

在设置视图中填入你的大模型 API 信息：

- **LLM API**：OpenAI 兼容接口（Base URL + Key + Model）
- **插图 API**：图像生成接口
- **TTS**：本地文字转语音服务地址

> 不配置 API 时，系统使用 Mock 数据运行，可完整体验所有交互流程。

## 项目结构

```
StoryDive/
├── backend/server.py      # FastAPI 后端
├── frontend/index.html    # 单文件前端
├── books/                 # 剧本目录
│   ├── harry_potter/      #   哈利·波特与魔法石
│   └── three_body/        #   三体
└── saves/                 # 用户存档
```

## 操作说明

| 操作 | 方式 |
|------|------|
| 点击对话框 | 推进到下一段剧情 |
| 长按对话框 | 自动播放（1.5 秒/段） |
| Speak 模式 | 以主角身份说话 |
| Regret 模式 | 悔棋：回溯并改写历史 |
| Accelerate 模式 | 加速推进到原著下一关键节点 |
| 📖 图标 | 打开历史文本回顾，支持导出 |
