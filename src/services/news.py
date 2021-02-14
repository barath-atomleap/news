from typing import Dict, List
from grpc import ServicerContext, StatusCode
import proto.news_pb2 as service_pb2
import proto.news_pb2_grpc as service_pb2_grpc
from delphai_utils.validation import validate
from delphai_utils.logging import logging
from grpc.aio import AioRpcError
from delphai_discovery import get_service, call_model
from proto.proto.page_scraper_pb2_grpc import PageScraperStub
from proto.proto.translation_pb2_grpc import TranslationStub
from proto.proto.translation_pb2 import TranslateRequest, TranslateResponse
from proto.proto.page_scraper_pb2 import MetadataRequest, MetadataResponse, TextRequest, TextResponse
import asyncio

page_scraper = get_service('page-scraper', PageScraperStub, delphai_environment='common')
translation = get_service('translation', TranslationStub, delphai_environment='common')


def mask_company_names(companies: List[service_pb2.Company], text: str):
  masks: Dict[str, str] = {}
  for index, company in enumerate(companies):
    mask = f'<<NE{index}>>'
    text = text.replace(company.name, mask)
    masks[company.name]
  return text, masks


def unmask_company_names(masks: Dict[str, str], text: str):
  for company_name, mask in masks.items():
    text.replace(mask, company_name)
  return text


async def add_article(request: service_pb2.AddArticleRequest):
  logging.info(f'saving article from {request.url}')
  response = service_pb2.AddArticleResponse()
  metadata_task = page_scraper.get_metadata(MetadataRequest(url=request.url))
  text_task = page_scraper.get_text(TextRequest(url=request.url))
  tasks = [metadata_task, text_task]
  metadata_response, text_response = await asyncio.gather(*tasks)
  metadata: MetadataResponse = metadata_response
  text: TextResponse = text_response
  response.title = metadata.title
  response.date = metadata.date
  response.lang = metadata.lang
  response.content = text.text
  if metadata.lang != 'en':
    masked_title, title_masks = mask_company_names(request.companies, response.title)
    masked_content, content_masks = mask_company_names(request.companies, response.content)
    title_translation_task = translation.translate(TranslateRequest(text=masked_title, method='azure'))
    content_translation_task = translation.translate(TranslateRequest(text=masked_content, method='azure'))
    title, content = await asyncio.gather(title_translation_task, content_translation_task)
    response.translated_title = unmask_company_names(title_masks, title.translation)
    response.translated_content = unmask_company_names(content_masks, content.translation)

  model = 'ner-tagger'
  content = response.content
  if metadata.lang == 'de':
    model = 'ger-ner'
  elif metadata.lang != 'en':
    content = response.translated_content

  entities = await call_model(model, content)
  mentions = sorted(set(list(map(lambda entity: entity[0].strip(), entities['ORG']))))
  response.mentions.extend(mentions)
  return response


class News(service_pb2_grpc.News):
  async def add_article(self, request: service_pb2.AddArticleRequest, context: ServicerContext):
    await validate(service_pb2.AddArticleRequest, request, context)
    try:
      return await add_article(request)
    except AioRpcError as ex:
      await context.abort(ex.code, ex.details())
    except Exception as ex:
      await context.abort(StatusCode.INTERNAL, str(ex))