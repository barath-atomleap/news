from bson import ObjectId
import datetime
from delphai_backend_utils.db_access import get_own_db_connection
from utils.utils import clean_url, save_blob, is_text_in_english, translate_to_english
import logging
from news_processing import news_boilerplater, get_company_info_from_article, get_product_info_from_article

db = get_own_db_connection()
news = db.news
news.create_index('url', unique=True)
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
    company = db.companies.find_one({'url': clean_url(company_url)}, {'url': 1})
    title, content, date = news_boilerplater(html=html)
    # translate text if necessary
    if not is_text_in_english(title):
        title = translate_to_english(title)
    if not is_text_in_english(content):
        content = translate_to_english(content)
    # get company information
    news_snippet_about_company = get_company_info_from_article(company_name=company, content=content)
    # get product information
    product_keywords = ["product"]  # this list will be updated
    if news_snippet_about_company is not None:
        news_snippet_about_products = get_product_info_from_article(content="{}. {}".format(title, content),
                                                        keywords=product_keywords)
    else:
        news_snippet_about_products = None

    description, mentions, company_name = news_snippet_about_company, [news_snippet_about_products], company  # 'boilerplating(html)'
    html_ref = save_blob('news/' + clean_url(page_url), html)
    data = {
        'company_id': company['_id'],
        'url': page_url,
        'content': content,
        'title': title,
        'description': description,
        'mentions': mentions,
        'html_ref': html_ref,
        'date': datetime.datetime.strptime(str(date), '%Y-%m-%d')  #  datetime.datetime.now()
    }

    article_id = news.insert_one(data)

    # article_id = article.update_one(new_page.to_native(role='query'), {'$set': new_page.to_native(role='set')},
    #                                    upsert=True)
    return str(article_id.inserted_id)

  except Exception as e:
    logging.error(f'Error: {e}')
