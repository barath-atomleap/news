from bson import ObjectId
import datetime
from delphai_backend_utils.db_access import get_own_db_connection
from utils.utils import clean_url, save_blob, is_text_in_english, translate_to_english
import logging
from news_processing import news_boilerplater, get_company_info_from_article, get_product_info_from_article

db = get_own_db_connection()
news = db.news
# news.create_index('url', unique=True)
news.create_index('company_id')


def articles_data(company_id, start_row, fetch_count):

  skip = (start_row - 1) * fetch_count

  news_articles = news.aggregate([{
      "$match": {
          "company_id": ObjectId(company_id)
      }
  }, {
      "$project": {
          "_id": 0,
          "description": 1,
          "mentions": 1,
          "is_translated": 1,
          "date": {
              '$dateToString': {
                  'format': '%Y-%m-%d',
                  'date': {
                      '$toDate': '$date'
                  }
              }
          },
          "title": 1,
          "url": 1
      }
  }, {
      "$sort": {
          "date": -1
      }
  }, {
      "$facet": {
          "total": [{
              "$count": "count"
          }],
          "articles": [{
              "$skip": skip
          }, {
              "$limit": int(fetch_count)
          }]
      }
  }])

  results = list(news_articles)[0]
  results['total'] = results['total'][0].get('count', 0) if len(results['total']) > 0 else 0

  return results


def save_articles(company_url, page_url, html):
  try:
    is_translated = False
    company = db.companies.find_one({'url': clean_url(company_url)}, {'url': 1, 'name': 1})
    company_name = company.get('name')
    if type(company_name) is not str:
      logging.error(f'Error: Company "{company_name}" is not a string in the DB and cannot be processed by fuzzywuzzy')
      raise ValueError(f"Company '{company_name}' is not a string in the DB and cannot be processed by fuzzywuzzy")
    title, content, date = news_boilerplater(html=html)
    if title is not None and content is not None and date is not None:
      # translate text if necessary
      if not is_text_in_english(title):
        is_translated = True
        title = translate_to_english(title)
      if not is_text_in_english(content):
        is_translated = True
        content = translate_to_english(content)
      # logging.debug(f'title: {title}')
      # logging.debug(f'date: {date}')
      # get company information
      news_snippet_about_company = get_company_info_from_article(company_name=company_name,
                                                                 content="{}. {}".format(title, content))

      if news_snippet_about_company:
        # get product information
        product_keywords = ["product"]  # this list will be updated
        if news_snippet_about_company is not None:
          news_snippet_about_products = get_product_info_from_article(content="{}. {}".format(title, content),
                                                                      keywords=product_keywords)
        else:
          news_snippet_about_products = None

        html_ref = save_blob('news/' + clean_url(page_url), html)
        data = {
            'company_id': company['_id'],
            'url': page_url,
            'content': content,
            'title': title,
            'description': news_snippet_about_company,
            'mentions': [company_name],
            'prod_desc': news_snippet_about_products,
            # 'prod_mentions': mentions,
            'html_ref': html_ref,
            'date': datetime.datetime.strptime(str(date), '%Y-%m-%d')  #  datetime.datetime.now()
        }
        if is_translated:
          data['is_translated'] = is_translated

        article_id = news.insert_one(data)

        # article_id = article.update_one(new_page.to_native(role='query'), {'$set': new_page.to_native(role='set')},
        #                                    upsert=True)
        return str(article_id.inserted_id)

  except Exception as e:
    logging.error(f'Error: {e}')


def products_data(company_id, start_row, fetch_count):

  skip = (start_row - 1) * fetch_count

  news_articles = news.aggregate([{
      "$match": {
          "company_id": ObjectId(company_id),
          "prod_desc": {
              '$exists': 1
          }
      }
  }, {
      "$project": {
          "_id": 0,
          "description": '$prod_desc',
          "mentions": '$prod_mentions',
          "is_translated": 1,
          "date": {
              '$dateToString': {
                  'format': '%Y-%m-%d',
                  'date': {
                      '$toDate': '$date'
                  }
              }
          },
          "title": 1,
          "url": 1
      }
  }, {
      "$sort": {
          "date": -1
      }
  }, {
      "$facet": {
          "total": [{
              "$count": "count"
          }],
          "articles": [{
              "$skip": skip
          }, {
              "$limit": int(fetch_count)
          }]
      }
  }])

  results = list(news_articles)[0]
  results['total'] = results['total'][0].get('count', 0) if len(results['total']) > 0 else 0

  return results
