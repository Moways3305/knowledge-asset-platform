# Backend image — FastAPI + Celery 共用镜像（backend / worker / beat / migrate）。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 先装锁定依赖（requirements.lock 由 `uv pip compile pyproject.toml build-requirements.in
# -o requirements.lock --python-version 3.12 --python-platform linux --generate-hashes`
# 生成，含运行时依赖与 PEP 517 build backend）。lock 不变时该层命中缓存，
# 改业务代码不会触发依赖重装；--require-hashes 保证可重现。
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# 再装应用本体。--no-deps：依赖已由 lock 层固定；--no-build-isolation：复用上面
# 已锁定安装的 build backend（hatchling），不在构建时临时下载未锁定依赖。
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --no-deps --no-build-isolation .

COPY alembic.ini ./
COPY alembic ./alembic

# 非 root 运行。/app 目录属主给 appuser（celery beat 需在 CWD 写 celerybeat-schedule）；
# /data/uploads 预建并授权，使**新建**的命名卷在首挂载时继承 appuser 属主。
# 注意：已存在的 upload_storage 卷仍是 root 属主，升级镜像后需重建卷或手动 chown。
RUN useradd --system --create-home appuser \
    && chown appuser:appuser /app \
    && mkdir -p /data/uploads \
    && chown appuser:appuser /data/uploads
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
