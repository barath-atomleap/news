import sys
sys.path.append('./src/proto')
from google.protobuf.json_format import MessageToDict
from delphai_utils.grpc_server import create_grpc_server, start_server
import proto.news_pb2 as service_pb2
import proto.news_pb2_grpc as service_pb2_grpc
from services.articles import articles_data, save_article
from delphai_utils.logging import logging
logging.getLogger('azure').setLevel(logging.ERROR)


class News(service_pb2_grpc.News):
  async def get_articles(self, request: service_pb2.ArticlesRequest, context):
    company_id = request.company_id
    start_row = request.start_row if request.start_row else 1
    fetch_count = request.fetch_count if request.fetch_count else 10
    articles = articles_data(company_id, start_row, fetch_count)
    return service_pb2.ArticlesResponse(articles=articles.get('articles', []), total_articles=articles.get('total', 0))

  async def add_articles(self, request: service_pb2.AddArticlesRequest, context):
    request_dict = MessageToDict(request, preserving_proto_field_name=True)
    article = save_article(request_dict.get('companies'), request_dict.get('url'), request_dict.get('html'),
                           request_dict.get('test_mode'), request_dict.get('source'), request_dict.get('date'),
                           request_dict.get('get_named_entities'), request_dict.get('no_products'),
                           request_dict.get('topic'), request_dict.get('title'), request_dict.get('content'),
                           request_dict.get('translate', True))
    return service_pb2.AddArticlesResponse(article_ids=article.get('article_ids', []),
                                           title=article.get('title', ''),
                                           content=article.get('content', ''),
                                           message=article.get('message', ''),
                                           date=article.get('date', ''))


if __name__ == "__main__":
  server = create_grpc_server(service_pb2.DESCRIPTOR)
  service_pb2_grpc.add_NewsServicer_to_server(News(), server=server)
  start_server(server)
