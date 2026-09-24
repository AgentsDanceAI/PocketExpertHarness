FROM python:3.12-slim

# 国内构建可传 --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 \
    PEH_IN_CONTAINER=1 PEH_HOME=/data PEH_WORKSPACE=/data/workspace PEH_HOST=0.0.0.0 PEH_PORT=8080

# Node 让 npx 类 MCP 服务 (如 @modelcontextprotocol/server-filesystem) 能直接用; 数据分析常用库给 run_python
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm fonts-noto-cjk ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install pandas matplotlib openpyxl

WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY pocketexpert_harness ./pocketexpert_harness
RUN pip install . && useradd -m -u 1000 peh && mkdir -p /data/workspace && chown -R peh /data
USER peh
VOLUME ["/data"]
EXPOSE 8080
CMD ["peh", "serve"]
