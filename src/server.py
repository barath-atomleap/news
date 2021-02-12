import sys
sys.path.append('./src/proto')

import asyncio
from delphai_utils.grpc_server import create_grpc_server, start_server
import proto.news_pb2 as service_pb2
import proto.news_pb2_grpc as service_pb2_grpc
from delphai_utils import validation
from services.news import News
from grpc import StatusCode

if __name__ == "__main__":
  server = create_grpc_server(service_pb2.DESCRIPTOR)
  service_pb2_grpc.add_NewsServicer_to_server(News(), server=server)
  start_server(server)