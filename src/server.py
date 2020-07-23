import service_pb2_grpc
import service_pb2
import grpc
from grpc_reflection.v1alpha import reflection
from concurrent import futures
from delphai_backend_utils import logging
from articles import articles_data, save_articles


class Articles(service_pb2_grpc.Articles):
  def get_articles(self, request, context):
    company_id = request.company_id
    start_row = request.start_row
    fetch_count = request.fetch_count
    articles = articles_data(company_id, start_row, fetch_count)
    return service_pb2.ArticlesResponse(articles=articles.get('articles', []), total_articles=articles.get('total', 0))

  def add_articles(self, request, context):
    company_url = request.company_url
    date = request.date
    page_url = request.url
    html = request.html
    article = save_articles(company_url, page_url, html, date)
    return service_pb2.AddArticlesResponse(article_id=article)


def serve():
  server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
  service_pb2_grpc.add_ArticlesServicer_to_server(Articles(), server)

  # the reflection service will be aware of "Greeter" and "ServerReflection" services.
  service_names = (
      service_pb2.DESCRIPTOR.services_by_name['Articles'].full_name,
      reflection.SERVICE_NAME,
  )
  reflection.enable_server_reflection(service_names, server)

  address = '0.0.0.0:8080'
  server.add_insecure_port(address)
  server.start()
  logging.info(f'Started server {address}')
  try:
    server.wait_for_termination()
  except KeyboardInterrupt:
    logging.error('Interrupted')


if __name__ == '__main__':
  serve()
