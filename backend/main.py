"""后端启动入口（uvicorn）。

用法（在 backend 目录下）：

    conda run -n devpipeline python main.py                # 127.0.0.1:8000
    conda run -n devpipeline python main.py --port 8010
    conda run -n devpipeline python main.py --reload       # 开发热重载，只监听 app/ 目录
    conda run -n devpipeline python main.py --host 0.0.0.0 # 局域网可访问

也可以用环境变量：API_HOST / API_PORT / API_RELOAD / API_LOG_LEVEL。
启动实现见 app/core/server.py（`python -m app` 走同一份）。
"""

from app.core.server import run

if __name__ == "__main__":
    run()
