FROM debian:trixie

COPY install_dependencies.sh /tmp/install_dependencies.sh

RUN chmod +x /tmp/install_dependencies.sh && \
    /tmp/install_dependencies.sh && \
    rm /tmp/install_dependencies.sh

# Create the user used by Jenkins Docker Pipeline
RUN useradd -m -s /bin/bash jenkins

# Create a ccache directory writable by Jenkins
RUN mkdir -p /var/cache/ccache && \
    chown -R jenkins:jenkins /var/cache/ccache

ENV CCACHE_DIR=/var/cache/ccache

WORKDIR /workspace

USER jenkins
