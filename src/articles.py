from bson import ObjectId
from delphai_backend_utils.db_access import get_own_db_connection
from utils.utils import clean_url, save_blob
import logging

db = get_own_db_connection()
articles = db.articles
articles.create_index('url', unique=True)
articles.create_index('company_id')


def articles_data(company_id, start_row, fetch_count):

  skip = (start_row - 1) * fetch_count

  news_articles = articles.aggregate([{
      "$match": {
          "company_id": ObjectId(company_id)
      }
  }, {
      "$project": {
          "_id": 0,
          "location": 1,
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
          "posts": [{
              "$skip": skip
          }, {
              "$limit": int(fetch_count)
          }]
      }
  }])

  results = list(news_articles)[0]
  #   print(results)

  return results


def save_articles(company_url, page_url, html, date):
  try:
    company = db.companies.find_one({'url': clean_url(company_url)}, {'url': 1})
    text, title, scope = 'boilerplating(html)'
    html_ref = save_blob('articles/' + clean_url(page_url), html)
    data = {
        'company_id': company['_id'],
        'url': page_url,
        'text': text,
        'title': title,
        'scope': scope,
        'html_ref': html_ref,
        'date': date  #  datetime.datetime.now()
    }

    article_id = articles.insert_one(data)

    # article_id = article.update_one(new_page.to_native(role='query'), {'$set': new_page.to_native(role='set')},
    #                                    upsert=True)
    res = {}
    res['content_id'] = str(article_id.upserted_id if article_id.upserted_id else '')
    res['company_url'] = company['url']
    res['company_id'] = str(company['_id'])
    return res

  except Exception as e:
    logging.error(f'Error: {e}')
