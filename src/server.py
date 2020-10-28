import sys

from delphai_utils.grpc_server import create_grpc_server, start_server
import proto.news_pb2 as service_pb2
import proto.news_pb2_grpc as service_pb2_grpc
from services.articles import articles_data, save_article, products_data
sys.path.append('./src/proto')


class News(service_pb2_grpc.News):
  async def get_articles(self, request, context):
    company_id = request.company_id
    start_row = request.start_row if request.start_row else 1
    fetch_count = request.fetch_count if request.fetch_count else 10
    articles = articles_data(company_id, start_row, fetch_count)
    return service_pb2.ArticlesResponse(articles=articles.get('articles', []), total_articles=articles.get('total', 0))

  async def add_articles(self, request, context):
    article = save_article(request.get('companies'), request.get('url'), request.get('html'), request.get('test_mode'),
                           request.get('date'))
    return service_pb2.AddArticlesResponse(article_ids=article.get('article_ids', []),
                                           title=article.get('title', ''),
                                           content=article.get('content', ''),
                                           message=article.get('message', ''))

  async def get_products(self, request, context):
    company_id = request.company_id
    start_row = request.start_row
    fetch_count = request.fetch_count
    articles = products_data(company_id, start_row, fetch_count)
    return service_pb2.ArticlesResponse(articles=articles.get('articles', []), total_articles=articles.get('total', 0))


if __name__ == "__main__":
  server = create_grpc_server(service_pb2.DESCRIPTOR)
  service_pb2_grpc.add_NewsServicer_to_server(News(), server=server)
  start_server(server)
