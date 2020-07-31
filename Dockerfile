FROM python:3.8
WORKDIR /app
RUN pip install pipenv
ENV PIPENV_VENV_IN_PROJECT=true 
COPY Pipfile Pipfile.lock service.proto /app/
RUN pipenv lock -r > requirements.txt
RUN pip install -r requirements.txt
RUN mkdir -p ./src && python -m grpc_tools.protoc -I. --python_out=./src --grpc_python_out=./src ./service.proto
COPY . /app
ENTRYPOINT [ "python", "src/server.py" ]