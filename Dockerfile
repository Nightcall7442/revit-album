# Space Design Album - web home of the agent (Railway). The plugin itself is the repository root.

# LibreDWG (GPLv3): DXF -> DWG for the studio's draftsman (dxf2dwg) and DWG input (dwg2dxf). Pinned commit, three programs.
FROM python:3.13-slim AS libredwg
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ARG LIBREDWG_SHA=f860b0fb76d5f8effb5a70769a3389cb1e0308c8
RUN git init /src && cd /src && git remote add origin https://github.com/LibreDWG/libredwg.git \
    && git fetch --depth 1 origin ${LIBREDWG_SHA} && git checkout FETCH_HEAD \
    && git submodule update --init --depth 1 \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release -DLIBREDWG_DISABLE_WERROR=ON \
    && make -j4 dxf2dwg dwgread dwg2dxf \
    && mkdir -p /out/bin /out/lib && cp dxf2dwg dwgread dwg2dxf /out/bin/ && cp -P libredwg.so* /out/lib/

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg DATA_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends fontconfig && rm -rf /var/lib/apt/lists/*
COPY --from=libredwg /out/bin/ /usr/local/bin/
COPY --from=libredwg /out/lib/ /usr/local/lib/
RUN ldconfig && dxf2dwg --version
WORKDIR /app
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY . .
RUN cd skills/design-album/scripts && python sda.py doctor
EXPOSE 8080
CMD ["sh", "-c", "uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
