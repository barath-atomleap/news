# migrate grpc service
FROM python:3.8 as build
WORKDIR /app
ENV PATH /root/.poetry/bin:$PATH
RUN apt update && apt install -y curl
RUN curl -sSL https://github.com/stormcat24/protodep/releases/download/0.0.8/protodep_linux_amd64.tar.gz > protodep_linux_amd64.tar.gz
RUN tar -xf protodep_linux_amd64.tar.gz && mv protodep /usr/local/bin/
RUN curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python
ENV PATH /root/.poetry/bin:$PATH
COPY pyproject.toml protodep.toml protodep.lock /app/
COPY ./proto /app/proto
RUN poetry install
RUN poetry run poe codegen
COPY ./proto /app/proto
RUN true
COPY ./src /app/src
COPY ./config /app/config
ENTRYPOINT [ "poetry", "run", "python", "src/server.py" ]
