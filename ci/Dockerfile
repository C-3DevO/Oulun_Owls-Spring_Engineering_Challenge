FROM debian:trixie

COPY install_dependencies.sh /tmp/install_dependencies.sh

RUN chmod +x /tmp/install_dependencies.sh && \
    /tmp/install_dependencies.sh && \
    rm /tmp/install_dependencies.sh

WORKDIR /workspace
