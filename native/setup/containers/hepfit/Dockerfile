# Coordinator supplies digest-pinned dependencies and verified source bytes.
# BASE_IMAGE includes @sha256:<64 hex> and provides ROOT, BAT, GSL, Boost, MPI, CMake.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG SOURCE_SHA256
COPY source.tar.gz /tmp/source.tar.gz
RUN test -n "$SOURCE_SHA256" && echo "$SOURCE_SHA256  /tmp/source.tar.gz" | sha256sum -c - \
 && mkdir -p /opt/hepfit-source \
 && tar -xzf /tmp/source.tar.gz --strip-components=1 -C /opt/hepfit-source \
 && cmake -S /opt/hepfit-source -B /tmp/hepfit-build \
      -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/hepfit \
      -DFETCHCONTENT_FULLY_DISCONNECTED=ON -DFETCHCONTENT_UPDATES_DISCONNECTED=ON \
 && cmake --build /tmp/hepfit-build --parallel 2 \
 && cmake --install /tmp/hepfit-build \
 && rm -rf /tmp/source.tar.gz /tmp/hepfit-build
ENV PATH="/opt/hepfit/bin:${PATH}"
