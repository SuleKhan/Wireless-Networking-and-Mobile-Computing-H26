# audiowmark 0.6.5 + WNMC capacity patch
#   adds --payload-size N  (message length, default 128)
#   adds --generators N    (error-correction strength, even 2..12, default 12)
# Build:  docker build -t wnmc-audiowmark .
# Use:    docker run --rm -v "<folder>:/data" wnmc-audiowmark add in.wav out.wav <hex>

FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential automake autoconf libtool autoconf-archive gettext pkg-config \
        git ca-certificates \
        libfftw3-dev libsndfile1-dev libgcrypt20-dev libzita-resampler-dev libmpg123-dev \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch 0.6.5 https://github.com/swesterfeld/audiowmark.git /src
COPY audiowmark-capacity.patch /src/
WORKDIR /src
# 1) strip CRs: a Windows checkout or a zip download can give the patch CRLF endings, which
#    git apply rejects
# 2) ACLOCAL_AMFLAGS conflicts with AC_CONFIG_MACRO_DIR on current libtool; the macro dir is still used
RUN sed -i 's/\r$//' audiowmark-capacity.patch \
 && git apply --whitespace=nowarn audiowmark-capacity.patch \
 && sed -i '/^ACLOCAL_AMFLAGS/d' Makefile.am \
 && ./autogen.sh && make -j"$(nproc)" && make install

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        libfftw3-single3 libfftw3-double3 libsndfile1 libgcrypt20 libzita-resampler1 libmpg123-0 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local/bin/audiowmark /usr/local/bin/audiowmark
WORKDIR /data
ENTRYPOINT ["/usr/local/bin/audiowmark"]
